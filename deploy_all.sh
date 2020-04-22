#!/bin/bash
#
kubectl apply -f critical-service-crd.yaml
kubectl apply -f critical-service-pod-template.yaml
kubectl apply -f authorization-v5.yaml
kubectl apply -f configmap.yaml
kubectl apply -f controller-depl-cm-v5.yaml
kubectl apply -f critical-service.yaml
kubectl apply -f service.yaml
kubectl apply -f nginx-pod.yaml
