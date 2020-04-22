import asyncio
import logging

from kubernetes import client, config, watch

logger = logging.getLogger('k8s_events')
logger.setLevel(logging.INFO)

config.load_kube_config()

v1 = client.CoreV1Api()
#v1ext = client.ExtensionsV1beta1Api()

async def pods():
    print('pods')
    w = watch.Watch()
    for event in w.stream(v1.list_pod_for_all_namespaces):
        print('pod loop')
        logger.info("Event: %s %s %s" % (event['type'], event['object'].kind, event['object'].metadata.name))
        print("Event: %s %s %s" % (event['type'], event['object'].kind, event['object'].metadata.name))
        await asyncio.sleep(0) 
    
async def deployments():
    print('depls')
    w = watch.Watch()
    for event in w.stream(v1.list_service_for_all_namespaces):
        print('depl loop')
        logger.info("Event: %s %s %s" % (event['type'], event['object'].kind, event['object'].metadata.name))
        print("Event: %s %s %s" % (event['type'], event['object'].kind, event['object'].metadata.name))
        await asyncio.sleep(0)

ioloop = asyncio.get_event_loop()

ioloop.create_task(pods())
ioloop.create_task(deployments())
ioloop.run_forever()
