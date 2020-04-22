'''
Ce script surveille les Services et les POD et génère des
warnings quand un Service devient bancal (sans Endpoint).

Si des CriticalService sont définis, le script lance un POD
par défaut pour assurer que le Service ait un Endpoint. Quand le
Service recouvre un véritable Endpoint, le POD supplétif est 
supprimé.
'''
import os
import sys
import urllib3
import logging
from multiprocessing import Process, Queue
from kubernetes import client, config, watch
from kubernetes.client import Configuration
from kubernetes.client.rest import ApiException

urllib3.disable_warnings()

if len(sys.argv) > 1:
    config.load_kube_config(sys.argv[1])
else:
    try:
        config.load_kube_config()
    except:
        config.load_incluster_config()

# Ces variables peuvent être surchargées via des variables d'environnement
pod_name_prefix = os.environ['POD_NAME_PREFIX'] if 'POD_NAME_PREFIX' in os.environ else 'service-watcher'
pod_template = os.environ['POD_TEMPLATE'] if 'POD_TEMPLATE' in os.environ else 'critical-service-pod-template'
pod_template_ns = os.environ['POD_TEMPLATE_NS'] if 'POD_TEMPLATE_NS' in os.environ else 'linux-mag'
log_level = os.environ['LOG_LEVEL'] if 'LOG_LEVEL' in os.environ else logging.WARNING
try:
    logging.basicConfig(level=log_level)
except Exception as e:
    logging.error(f"Bad value for environment variable LOG_LEVEL: {os.environ['LOG_LEVEL']}")

try:
    ns = os.environ['NAMESPACES'].split(',') if 'NAMESPACES' in os.environ else []
except Exception as e:
    logging.error(f"Bad value for environment variable NAMESPACES: {os.environ['NAMESPACES']}")
    ns = []

v1 = client.CoreV1Api()
custom_api = client.CustomObjectsApi()


def watch_services(q):
    w = watch.Watch()
    for event in w.stream(v1.list_service_for_all_namespaces):
        metadata = event['object'].metadata
        spec = event['object'].spec
        logging.info(f"Event {event['type']}, Service Name: {metadata.name}, Service Type: {spec.type}, Namespace: {metadata.namespace}")

        if not len(ns) or metadata.namespace in ns:
            q.put(event)


def watch_pods(q):
    w = watch.Watch()
    for event in w.stream(v1.list_pod_for_all_namespaces):
        metadata = event['object'].metadata
        spec = event['object'].spec
        logging.info(f"Event {event['type']}, POD Name: {metadata.name}, Namespace: {metadata.namespace}")

        if not len(ns) or metadata.namespace in ns:
            q.put(event)


def watch_critical_services(q):
    w = watch.Watch()
    for event in w.stream(custom_api.list_cluster_custom_object, group="mycrd.com", version="v1", plural="criticalservices"):
        metadata = event['object']['metadata']
        logging.info(f"Event {event['type']}, CriticalService Name: {metadata['name']}")
        q.put(event)


def handle_events(q):
    '''
    Boucle de gestion des événements publiés par les Watchers.
    Il ya 3 types d'évts: les Services, les POD et les CriticalServices
    '''
    lame_svc = []       # liste des Services bancals
    critical_svc = {}   # dict des CriticalServices

    while True:
        event = q.get()

        # Evénement pour les CriticalServices
        if not hasattr(event['object'], 'kind'):
            metadata = event['object']['metadata']
            spec = event['object']['spec']

            if event['object']['kind'] != 'CriticalService':
                continue

            # Mémorise le CriticalService ou bien le met à jour ou le détruit
            if event['type'] == 'DELETED':
                if metadata['name'] in critical_svc:
                    _delete_critical_svc(metadata['name'], spec)
                    del critical_svc[metadata['name']]
            else: # ADDED ou MODIFIED
                critical_svc[metadata['name']] = spec 
                _check_critical_svc(metadata['name'], spec)
            continue

        metadata = event['object'].metadata
        spec = event['object'].spec

        # Evénément pour les Services
        if event['object'].kind == 'Service':
            # Ignore les Services de type ExternalName ou ceux qui n'ont pas de 
            # "selector" comme l'API-Server ou ceux qui sont en cours de suppression
            selector = spec.selector
            if selector is None or spec.type == 'ExternalName' or event['type'] == 'DELETED':
                logging.debug(f"Skip Service {metadata.name}")

                # Détruit le POD par défaut si nécessaire
                if _is_critical_svc(metadata, critical_svc):
                    _delete_default_pod(event['object'])
                continue

            # Cherche les POD correspondant au "selector"
            selectors = [f"{k}={v}" for k, v in spec.selector.items()]
            pods = v1.list_namespaced_pod(metadata.namespace, watch=False, label_selector=','.join(selectors))
            if not len(pods.items):
                if metadata.name not in lame_svc:
                    logging.warning(f"Service {metadata.name} from Namespace {metadata.namespace} has no selected POD")
                    lame_svc.append(metadata.name)
                    logging.info(f"Lame Services={lame_svc}")

                    # Crée le POD par défaut si nécessaire
                    if _is_critical_svc(metadata, critical_svc):
                        _create_default_pod(event['objet'])

        # Evénement pour les POD
        elif event['object'].kind == 'Pod':
            if event['type'] == 'ADDED' or event['type'] == 'MODIFIED':
                _check_all_svc(lame_svc, critical_svc, metadata.namespace, event['type'])
            elif event['type'] == 'DELETED':
                _check_all_svc(lame_svc, critical_svc, metadata.namespace, event['type'])


def _check_all_svc(lame_svc, critical_svc, pod_namespace, pod_event_type):
    '''
    Fonction appelée quand un événement sur un POD est survenu.
    Il faut vérifier si l'ajout, la modification ou la destruction
    du POD (donné par pod_event_type) a rendu un Service bancal
    ou non dans le namespace indiqué.
    La liste des Services bancals est alors mise à jour.
    Si le Service est dans la liste des CriticalServices, il faut
    aussi gérer le POD par défaut.
    '''
    services = v1.list_namespaced_service(pod_namespace, watch=False)
    for svc in services.items:
        metadata = svc.metadata
        spec = svc.spec

        if len(ns) and not metadata.namespace in ns:
            continue

        selector = spec.selector
        if selector is None or spec.type == 'ExternalName':
            logging.debug(f"Skip Service {metadata.name}")
            continue

        # Cherche les POD correspondant au "selector"
        selectors = [f"{k}={v}" for k, v in spec.selector.items()]
        pods = v1.list_namespaced_pod(pod_namespace, watch=False, label_selector=','.join(selectors))

        # Crée un POD par défaut si le Service devient bancal
        if not len(pods.items) and (pod_event_type == 'DELETED' or pod_event_type == 'MODIFIED'):
            if metadata.name not in lame_svc:
                logging.warning(f"Service {metadata.name} from Namespace {metadata.namespace} has no selected POD")
                lame_svc.append(metadata.name)
                logging.info(f"Lame Services={lame_svc}")
                if _is_critical_svc(metadata, critical_svc):
                    _create_default_pod(svc)

        # Détruit le POD par défaut si le nombre de POD est > 1 sinon on risque de détruire le POD par défaut !
        if len(pods.items) and pod_event_type == 'ADDED':
            if metadata.name in lame_svc:
                logging.warning(f"Service {metadata.name} from Namespace {metadata.namespace} now has {len(pods.items)} selected POD(s)")
                lame_svc.remove(metadata.name)
                logging.info(f"Lame Services={lame_svc}")
            if len(pods.items) > 1 and _is_critical_svc(metadata, critical_svc):
                _delete_default_pod(svc)


def _is_critical_svc(svc_metadata, critical_svc):
    '''
    retourne un booléen qui indique si le service décrit pas svc_metadata
    est un CriticalService défini dans critical_svc.
    '''
    if svc_metadata.name not in critical_svc:
        return False

    return svc_metadata.namespace == critical_svc[svc_metadata.name]['namespace']
       

def _check_critical_svc(svc_name, spec):
    '''Le CriticalService dont le nom est "svc_name" et la spécification est "spec"
       a été créé ou modifié: il faut vérifier si cela impacte un Service déjà 
       existant. '''
    logging.info(f"Check CriticalService {svc_name} impact")

    # Cherche les Services correspondant à la définition du CriticalService
    services = v1.list_namespaced_service(spec['namespace'], watch=False)
    for svc in services.items:
        if _svc_matches_critical_svc(svc, spec):
            logging.info(f"Service {svc.metadata.namespace}/{svc.metadata.name} matches !")

            # Cherche les POD correspondant au "selector"
            selectors = [f"{k}={v}" for k, v in svc.spec.selector.items()]
            pods = v1.list_namespaced_pod(spec['namespace'], watch=False, label_selector=','.join(selectors))
            if not len(pods.items): 
                _create_default_pod(svc)


def _delete_critical_svc(svc_name, spec):
    '''Le CriticalService dont le nom est "svc_name" et la spécification est "spec"
       a été détruit: il faut vérifier si cela impacte un Service déjà existant
       en détruisant un POD par défaut.'''
    logging.info(f"Delete CriticalService {svc_name} impact")

    # Cherche les Services correspondant à la définition du CriticalService
    services = v1.list_namespaced_service(spec['namespace'], watch=False)
    for svc in services.items:
        if _svc_matches_critical_svc(svc, spec):
            logging.info(f"Service {svc.metadata.namespace}/{svc.metadata.name} matches !")
            _delete_default_pod(svc)


def _svc_matches_critical_svc(svc, spec):
    '''Détermine si le Service défini par "svc" correspond
       au CriticalService défini par "spec".'''

    # Compare les Labels du Service avec les matchLabels du CriticalService
    for matchLabel in spec['matchLabels']:
        if svc.metadata.labels is None:
            return False
        if matchLabel['key'] not in svc.metadata.labels:
            return False
        if matchLabel['value'] != svc.metadata.labels[matchLabel['key']]:
            return False

    return True


def _create_default_pod(svc):
    '''Pour créer un POD, nous devons déjà récupérer le POD Template, puis nous donnerons
       au POD, les labels attendus par le Service ainsi qu'une Annotation
       qui nous permettra de le repérer plus facilement.''' 
    metadata = svc.metadata
    logging.info(f"Create Default POD from POD Template {pod_template} for Service {metadata.namespace}/{metadata.name}")

    resp = None
    try:
        resp = v1.read_namespaced_pod_template(name=pod_template, namespace=pod_template_ns)
    except ApiException as e:
        logging.error("read_namespaced_pod_template error: %s" % e)
        return

    # Création de la Spec du POD à lancer
    pod_manifest = {
        'apiVersion': 'v1',
        'kind': 'Pod',
        'metadata': {
            'namespace': metadata.namespace,
            'name': pod_name_prefix + '-' + metadata.name,
            'labels': svc.spec.selector,
            'annotations': { 'service-watcher': 'owned' },
        },
        'spec': resp.template.spec
    }

    try:
        resp = v1.create_namespaced_pod(body=pod_manifest, namespace=metadata.namespace)
        logging.info("POD created")
    except ApiException as e:
        logging.error("create_namespaced_pod error: %s" % e)


def _delete_default_pod(svc):
    '''Soit un Service est détruit, soit un POD a été modifié: il faut vérifier
       si le Service defini par "metadata" possède un POD par défaut.
       Si tel est le cas, il faut le détruire.'''
    metadata = svc.metadata
    logging.info(f"Delete Default POD for Service {metadata.namespace}/{metadata.name}")

    resp = None
    try:
        # On essaye toujours la destruction...
        resp = v1.delete_namespaced_pod(name=pod_name_prefix + '-' + metadata.name, namespace=metadata.namespace)
        logging.info("POD deleted")
    except ApiException as e:
        logging.error("delete_namespaced_pod error: %s" % e)


# Programme principal !
q = Queue()
procs = [
            Process(target=watch_services, args=(q,)), 
            Process(target=watch_pods, args=(q,)), 
            Process(target=watch_critical_services, args=(q,)),
            Process(target=handle_events, args=(q,)),
        ]
[p.start() for p in procs]
[p.join() for p in procs]
