import requests
import json
import urllib
import hmac
import hashlib
import base64
import docker
import os
from .utility import Utility
from .cert import Cert
from edgectl.host.dockerclient import EdgeDockerClient

label = "edgehubtest"

class ResponseError(Exception):
    def __init__(self, status_code, value):
        self.value = value
        self.status_code = status_code

    def message(self):
        return ("Code:{0}. Detail:{1}").format(self.status_code, self.value)
    
    def status(self):
        return self.status_code

class EdgeManager(object):
    def __init__(self, connectionstring, gateway, output):
        values = connectionstring.split(';')
        hostPrefix = 'HostName='
        devicePrefix = 'DeviceId='
        keyPrefix = 'SharedAccessKey='
        hostname = ''
        deviceId = ''
        key = ''

        for value in values:
            stripped = value.strip()
            if (stripped.startswith(hostPrefix)):
                self.hostname = stripped[len(hostPrefix):]
            elif (stripped.startswith(devicePrefix)):
                self.deviceId = stripped[len(devicePrefix):]
            elif (stripped.startswith(keyPrefix)):
                self.key = stripped[len(keyPrefix):]

        self.output = output
        self.gateway = gateway
        self.deviceUri = "{0}/devices/{1}".format(self.hostname, self.deviceId)
        self.utility = Utility(None, self.output)

    def _generateModuleConnectionStr(self, response):
        jsonObj = json.loads(response.content)
        moduleId = jsonObj['moduleId']
        deviceId = jsonObj['deviceId']
        sasKey = jsonObj['authentication']['symmetricKey']['primaryKey']
        hubTemplate = 'HostName={0};DeviceId={1};ModuleId={2};SharedAccessKey={3}'
        moduleTemplate = 'HostName={0};GatewayHostName={1};DeviceId={2};ModuleId={3};SharedAccessKey={4}'
        if (moduleId == '$edgeHub'):
            return hubTemplate.format(self.hostname, deviceId, moduleId, sasKey)
        else:
            return moduleTemplate.format(self.hostname, self.gateway, deviceId, moduleId, sasKey)
    
    def _generateRoutesEnvFromInputs(self, inputs):
        routes = ['routes__output=FROM /messages/modules/target/outputs/* INTO BrokeredEndpoint("/modules/input/inputs/print")']
        routeTemplate = 'routes__r{0}=FROM /messages/modules/input/outputs/{1} INTO BrokeredEndpoint("/modules/target/inputs/{2}")'
        for (idx, input) in enumerate(inputs):
            routes.append(routeTemplate.format(idx+1, input, input))

        return routes

    def addmodule(self, name):
        moduleUri = "https://{0}/devices/{1}/modules/{2}?api-version=2017-11-08-preview".format(self.hostname, self.deviceId, name)
        sas = self.utility.get_iot_hub_sas_token(self.deviceUri, self.key, None)
        res = requests.put(
            moduleUri,
            headers={
                "Authorization": sas,
                "Content-Type": "application/json"
            },
            data=json.dumps({
                'moduleId': name,
                'deviceId': self.deviceId
            })
        )
        if (res.ok != True):
            raise ResponseError(res.status_code, res.text)
        return self._generateModuleConnectionStr(res)
    
    def getmodule(self, name):
        moduleUri = "https://{0}/devices/{1}/modules/{2}?api-version=2017-11-08-preview".format(self.hostname, self.deviceId, name)
        sas = self.utility.get_iot_hub_sas_token(self.deviceUri, self.key, None)
        res = requests.get(            
            moduleUri,
            headers={
                "Authorization": sas,
                "Content-Type": "application/json"
            }
        )
        if (res.ok != True):
            raise ResponseError(res.status_code, res.text)
        return self._generateModuleConnectionStr(res)
    

    def getOrAddModule(self, name):
        try:
            return self.getmodule(name)
        except ResponseError as geterr:
            if (geterr.status_code == 404):
                try:
                    return self.addmodule(name)
                except ResponseError as adderr:
                    output.error(geterr.message())
            else:
                output.error(adderr.message())
    
    @staticmethod
    def stop():
        dockerclient = docker.from_env()
        docker_api = docker.APIClient()
        edgedockerclient = EdgeDockerClient(dockerclient)
        edgedockerclient.stop_by_label(label)

    def teststart(self, inputs, certPath):
        edgeHubConstr = self.getOrAddModule('$edgeHub')
        edgeHubImg = 'microsoft/azureiotedge-hub:1.0-preview'

        inputConstr = self.getOrAddModule('input')
        inputImage = 'adashen/iot-edge-testing-utility:0.0.1'

        dockerclient = docker.from_env()
        docker_api = docker.APIClient()

        edgedockerclient = EdgeDockerClient(dockerclient)
        status = edgedockerclient.status("edgehub")
        if status != None: 
            edgedockerclient.stop("edgehub")
            edgedockerclient.remove("edgehub")
        status = edgedockerclient.status("input")
        if status != None:
            edgedockerclient.stop("input")
            edgedockerclient.remove("input")

        nw_name = 'azure-iot-edge'
        edgedockerclient.create_network(nw_name)
        network = dockerclient.networks.get(nw_name)
        edgedockerclient.create_volume('edgemoduletest')
        edgedockerclient.create_volume('edgehubtest')
        network_config = docker_api.create_networking_config({
            nw_name: docker_api.create_endpoint_config(
                aliases=[self.gateway]
            )
        })

        hubEnv = ["EdgeModuleHubServerCAChainCertificateFile=/mnt/edgehub/edge-chain-ca.cert.pem",
                    "EdgeModuleHubServerCertificateFile=/mnt/edgehub/edge-hub-server.cert.pfx",
                    "IotHubConnectionString={0}".format(edgeHubConstr),
                    "configSource=local"]
        hubEnv.extend(self._generateRoutesEnvFromInputs(inputs))
        hubContainer = docker_api.create_container(
            edgeHubImg,
            name='edgehub', 
            volumes=['/mnt/edgehub'],
            host_config=docker_api.create_host_config(
                mounts=[
                    docker.types.Mount('/mnt/edgehub', 'edgehubtest')
                ],
                port_bindings={
                    '8883/tcp': [
                        ('0.0.0.0', 8883),
                    ],
                    '443/tcp': 443
                }
            ),
            networking_config=network_config,
            environment=hubEnv,
            labels=[label],
            ports=[(8883, 'tcp'), (443, 'tcp')]
        )

        edgedockerclient.copy_file_to_volume('edgehub', 'edge-chain-ca.cert.pem', '/mnt/edgehub', os.path.join(certPath, 'edge-chain-ca', 'cert', 'edge-chain-ca.cert.pem'))
        edgedockerclient.copy_file_to_volume('edgehub', 'edge-hub-server.cert.pfx', '/mnt/edgehub', os.path.join(certPath, 'edge-hub-server', 'cert', 'edge-hub-server.cert.pfx'))
        docker_api.start(hubContainer.get('Id'))
        
        inputEnv = ["EdgeModuleCACertificateFile=/mnt/edgemodule/edge-device-ca.cert.pem",
                    "EdgeHubConnectionString={0}".format(inputConstr)]
        inputContainer = dockerclient.containers.create(
            inputImage,
            name='input',
            mounts=[
                docker.types.Mount('/mnt/edgemodule', 'edgemoduletest')
            ],
            network=nw_name,
            environment=inputEnv,
            labels=[label],
            ports={'3000/tcp':3000}
        )

        edgedockerclient.copy_file_to_volume('input', 'edge-device-ca.cert.pem', '/mnt/edgemodule', os.path.join(certPath, 'edge-device-ca', 'cert', 'edge-device-ca-root.cert.pem'))
        getattr(inputContainer, 'start')()
        return self.getOrAddModule('target')
        # targetConnstr =  self.getOrAddModule('target')
        # targetDeviceCert = os.path.join(certPath, 'edge-device-ca', 'cert', 'edge-device-ca-root.cert.pem')
        # with open('./.vocode/debug.env', 'w') as outfile:
        #     json.dump({
        #         'EdgeHubConnectionString': targetConnstr,
        #         'EdgeModuleHubServerCAChainCertificateFile': targetDeviceCert
        #     }, outfile)
        # return targetConnstr