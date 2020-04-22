'''
This script watches the Services and Pods and logs warnings when 
Services without any endpoints are detected.

The configuration filename that describes the K8s Cluster is given
on the command line.
'''
import sys
import urllib3
import logging
from multiprocessing import Process
from kubernetes import client, config, watch
from kubernetes.client import Configuration

urllib3.disable_warnings()

if len(sys.argv) > 1:
    config.load_kube_config(sys.argv[1])
else:
    config.load_kube_config()

logging.basicConfig(level=logging.DEBUG)
v1 = client.CoreV1Api()

def watch_services():
    w = watch.Watch()
    for event in w.stream(v1.list_service_for_all_namespaces):
        metadata = event['object'].metadata
        spec = event['object'].spec
        logging.debug(f"Event {event['type']}, Service Name: {metadata.name}, "
                      f"Service Type: {spec.type}, Namespace: {metadata.namespace}")

        # Ignore les Services de type ExternalName ou ceux qui n'ont pas de 
        # "selector" comme l'API-Server ou ceux qui sont en cours de suppression
        selector = spec.selector
        if selector is None or spec.type == 'ExternalName' or event['type'] == 'DELETED':
            logging.debug(f"Skip Service {metadata.name}")
            continue

        # Cherche les POD correspondant au "selector"
        selectors = [f"{k}={v}" for k, v in spec.selector.items()]
        pods = v1.list_namespaced_pod(metadata.namespace, watch=False, label_selector=','.join(selectors))
        if not len(pods.items):
            # Tests metadata.creation_timestamp of type datetime.datetime
            logging.warning(f"Service {metadata.name} from Namespace {metadata.namespace} "
                            f"has no selected POD")

    #w.stop()

def watch_pods():
    w = watch.Watch()
    for event in w.stream(v1.list_pod_for_all_namespaces):
        metadata = event['object'].metadata
        spec = event['object'].spec
        logging.debug(f"Event {event['type']}, POD Name: {metadata.name}, Namespace: {metadata.namespace}")

        # Si le type de l'événement est ADDED ou MODIFIED il faut vérifier si un Service
        # précédemment bancal dispose maintenant de Endpoints
        # Si le type de l'événement est DELETED il faut vérifier si un Service est devenu bancal
        if event['type'] == 'ADDED' or event['type'] == 'MODIFIED':
            pass
        elif event['type'] == 'DELETED':
            pass

    #w.stop()

proc_svc = Process(target=watch_services)
proc_pod = Process(target=watch_pods)
proc_svc.start()
proc_pod.start()
proc_svc.join()
proc_pod.join()

