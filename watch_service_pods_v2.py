'''
This script watches the Services and Pods and logs warnings when 
Services without any endpoints are detected.

The configuration filename that describes the K8s Cluster is given
on the command line.
'''
import sys
import urllib3
import logging
from multiprocessing import Process, Queue
from kubernetes import client, config, watch
from kubernetes.client import Configuration

urllib3.disable_warnings()

if len(sys.argv) > 1:
    config.load_kube_config(sys.argv[1])
else:
    config.load_kube_config()

logging.basicConfig(level=logging.INFO)
v1 = client.CoreV1Api()


def watch_services(q):
    w = watch.Watch()
    for event in w.stream(v1.list_service_for_all_namespaces):
        metadata = event['object'].metadata
        spec = event['object'].spec
        logging.debug(f"Event {event['type']}, Service Name: {metadata.name}, Service Type: {spec.type}, Namespace: {metadata.namespace}")
        q.put(event)

    #w.stop()


def watch_pods(q):
    w = watch.Watch()
    for event in w.stream(v1.list_pod_for_all_namespaces):
        metadata = event['object'].metadata
        spec = event['object'].spec
        logging.debug(f"Event {event['type']}, POD Name: {metadata.name}, Namespace: {metadata.namespace}")
        q.put(event)

    #w.stop()


def handle_events(q):
    lame_svc = []

    while True:
        event = q.get()
        metadata = event['object'].metadata
        spec = event['object'].spec

        if event['object'].kind == 'Service':
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
                if metadata.name not in lame_svc:
                    logging.warning(f"Service {metadata.name} from Namespace {metadata.namespace} has no selected POD")
                    lame_svc.append(metadata.name)

        elif event['object'].kind == 'Pod':
            if event['type'] == 'ADDED' or event['type'] == 'MODIFIED':
                _check_all_svc(lame_svc, metadata.namespace, event['type'])
            elif event['type'] == 'DELETED':
                _check_all_svc(lame_svc, metadata.namespace, event['type'])


def _check_all_svc(lame_svc, pod_namespace, pod_event_type):
    services = v1.list_namespaced_service(pod_namespace, watch=False)
    for svc in services.items:
        metadata = svc.metadata
        spec = svc.spec

        # Ignore les Services de type ExternalName ou ceux qui n'ont pas de 
        # "selector" comme l'API-Server 
        selector = spec.selector
        if selector is None or spec.type == 'ExternalName':
            logging.debug(f"Skip Service {metadata.name}")
            continue

        # Get the matching PODs
        selectors = [f"{k}={v}" for k, v in spec.selector.items()]
        pods = v1.list_namespaced_pod(pod_namespace, watch=False, label_selector=','.join(selectors))

        if not len(pods.items) and (pod_event_type == 'DELETED' or pod_event_type == 'MODIFIED'):
            if metadata.name not in lame_svc:
                logging.warning(f"Service {metadata.name} from Namespace {metadata.namespace} has no selected POD")
                lame_svc.append(metadata.name)
        if len(pods.items) and pod_event_type == 'ADDED':
            if metadata.name in lame_svc:
                logging.warning(f"Service {metadata.name} from Namespace {metadata.namespace} now has {len(pods.items)} selected POD(s)")
                lame_svc.remove(metadata.name)


q = Queue()
procs = [Process(target=watch_services, args=(q,)), Process(target=watch_pods, args=(q,)), Process(target=handle_events, args=(q,))]
[p.start() for p in procs]
[p.join() for p in procs]
