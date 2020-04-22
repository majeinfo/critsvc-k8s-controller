#!/bin/bash
#
kubectl delete -f controller-depl-cm-v5.yaml
kubectl delete -f configmap.yaml
kubectl delete -f critical-service.yaml
kubectl delete -f critical-service-pod-template.yaml
kubectl delete -f critical-service-crd.yaml
kubectl delete -f authorization-v5.yaml
kubectl delete -f nginx-pod.yaml
kubectl delete -f service.yaml
