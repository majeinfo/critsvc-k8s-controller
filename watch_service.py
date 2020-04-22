'''
Ce script surveille les Services et génére un message de log
quand un Service ne possède pas de Endpoint.
Pour se connecter à l'API-Server, on utilise le fichier
~/.kube/config ou bien le fichier de configuration donné en paramètre.
'''
import sys
import urllib3
import logging
from kubernetes import client, config, watch

urllib3.disable_warnings()

if len(sys.argv) > 1:
    config.load_kube_config(sys.argv[1])
else:
    config.load_kube_config()

logging.basicConfig(level=logging.INFO)

v1 = client.CoreV1Api()
w = watch.Watch()
for event in w.stream(v1.list_service_for_all_namespaces):
    metadata = event['object'].metadata
    spec = event['object'].spec
    logging.info(f"Event {event['type']}, Service Name: {metadata.name}, "
                 f"Service Type: {spec.type}, Namespace: {metadata.namespace}")

    # Ignore les Services de type ExternalName ou ceux qui n'ont pas de 
    # "selector" comme l'API-Server ou ceux qui sont en cours de suppression
    selector = spec.selector
    if selector is None or spec.type == 'ExternalName' or event['type'] == 'DELETED':
        logging.info(f"Skip Service {metadata.name}")
        continue

    # Cherche les POD correspondant au "selector"
    selectors = [f"{k}={v}" for k, v in spec.selector.items()]
    pods = v1.list_namespaced_pod(metadata.namespace, watch=False, label_selector=','.join(selectors))
    if not len(pods.items):
        logging.warning(f"Service {metadata.name} from Namespace {metadata.namespace} "
                        f"has no selected POD")

#w.stop()

