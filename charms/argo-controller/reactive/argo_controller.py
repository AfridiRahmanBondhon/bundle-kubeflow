import os
from pathlib import Path
from base64 import b64encode

import yaml
from charmhelpers.core import hookenv
from charms import layer
from charms.reactive import clear_flag, set_flag, when, when_any, when_not, endpoint_from_name


@when('charm.started')
def charm_ready():
    layer.status.active('')


@when_any('layer.docker-resource.oci-image.changed', 'config.changed')
def update_image():
    clear_flag('charm.started')


@when('layer.docker-resource.oci-image.available', 'minio.available')
@when_not('charm.started')
def start_charm():
    layer.status.maintenance('configuring container')

    minio = endpoint_from_name('minio').services()[0]['hosts'][0]

    image_info = layer.docker_resource.get_info('oci-image')

    crd = yaml.safe_load(Path("files/crd-v1alpha1.yaml").read_text())

    layer.caas_base.pod_spec_set(
        spec={
            'version': 2,
            'serviceAccount': {
                'global': True,
                'rules': [
                    {
                        'apiGroups': [''],
                        'resources': ['pods', 'pods/exec'],
                        'verbs': ['create', 'get', 'list', 'watch', 'update', 'patch'],
                    },
                    {
                        'apiGroups': [''],
                        'resources': ['configmaps'],
                        'verbs': ['get', 'watch', 'list'],
                    },
                    {
                        'apiGroups': [''],
                        'resources': ['persistentvolumeclaims'],
                        'verbs': ['create', 'delete'],
                    },
                    {
                        'apiGroups': ['argoproj.io'],
                        'resources': ['workflows'],
                        'verbs': ['get', 'list', 'watch', 'update', 'patch'],
                    },
                ],
            },
            'containers': [
                {
                    'name': 'argo-controller',
                    'command': ['workflow-controller'],
                    'args': ['--configmap', 'argo-controller-configmap-config'],
                    'imageDetails': {
                        'imagePath': image_info.registry_path,
                        'username': image_info.username,
                        'password': image_info.password,
                    },
                    'config': {'ARGO_NAMESPACE': os.environ['JUJU_MODEL_NAME']},
                    'files': [
                        {
                            'name': 'configmap',
                            'mountPath': '/config-map.yaml',
                            'files': {
                                'config': yaml.dump(
                                    {
                                        'executorImage': 'argoproj/argoexec:v2.3.0',
                                        'containerRuntimeExecutor': hookenv.config('executor'),
                                        'kubeletInsecure': hookenv.config('kubelet-insecure'),
                                        'artifactRepository': {
                                            's3': {
                                                'bucket': hookenv.config('bucket'),
                                                'keyPrefix': hookenv.config('key-prefix'),
                                                'endpoint': f'{minio["hostname"]}:{minio["port"]}',
                                                'insecure': True,
                                                'accessKeySecret': {
                                                    'name': 'mlpipeline-minio-artifact',
                                                    'key': 'accesskey',
                                                },
                                                'secretKeySecret': {
                                                    'name': 'mlpipeline-minio-artifact',
                                                    'key': 'secretkey',
                                                },
                                            }
                                        },
                                    }
                                )
                            },
                        }
                    ],
                }
            ],
        },
        k8s_resources={
            'kubernetesResources': {
                'customResourceDefinitions': {crd['metadata']['name']: crd['spec']},
                'secrets': [
                    {
                        'name': 'mlpipeline-minio-artifact',
                        'type': 'Opaque',
                        'data': {
                            'accesskey': b64encode(
                                hookenv.config('repo-access-key').encode('utf-8')
                            ),
                            'secretkey': b64encode(
                                hookenv.config('repo-secret-key').encode('utf-8')
                            ),
                        },
                    }
                ],
            }
        },
    )

    layer.status.maintenance('creating container')
    set_flag('charm.started')
