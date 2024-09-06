# Container Runner charm

[![Push (main)](https://github.com/canonical/app-center-ratings-operator/actions/workflows/push.yaml/badge.svg)](https://github.com/canonical/app-center-ratings-operator/actions/workflows/push.yaml)

The Container Runner charm aims to provide a configurable Charm for deploying simple backend web service and database setups onto Juju infrastructure. The aim is make it easier to deploy simple web applications without the need to create dedicated Charms for each service.

The Container Runner Charm provides:
- A running Docker engine snap for running OCI images.
- The ability to stop and restart the managed OCI image with different configuration.
- Configurable port setup for opening ports.
- Database relations passed into the running OCI image via environment variables.
- The ability to pass secrets into your running OCI image via environment variables.
- An instance of Watchtower to automatically update your OCI image when new images are pushed.

## Table of Contents

1. [Explanation](#explanation)
2. [Reference](#reference)
    - [Configuration Values](#configuration-values)
3. [How-to Guides](#how-to-guides)
    - [How to Setup a Development Environment](#how-to-setup-a-development-environment)
    - [How to Build the Charm Locally](#how-to-build-the-charm-locally)
    - [How to Deploy a Simple Web Application](#how-to-deploy-a-simple-web-application)
    - [How to Pass Secrets into the Running Container](#how-to-pass-secrets-into-the-running-container)
    - [How to Pass Non-Secret Config into the Running Container](#how-to-pass-non-secret-config-into-the-running-container)
    - [How to Connect to a Database](#how-to-connect-to-a-database)

# Explanation

The Container Runner charm works by installing the Docker Snap on install followed by pulling and running the Watchtower image. Watchtower allows for other OCI images being run by the Docker Snap to be automatically updated to their latest version. Next image specified under the `container-image-uri` config value is pulled and run.

The Container Runner charm is a machine charm, meaning that its required deployment environment is lxd.

Much of the lifecycle management of the Container Runner Charm is triggered by [Juju hooks](https://juju.is/docs/juju/hook).  Some key hooks that are used in this Charm include:
- `database_created`: Run when the Charm is related to a database. Will connect the Charm to the database to acquire credentials, then restart  the managed OCI image with an additional environment variable that can be used to connect to the database: `APP_POSTGRES_URI`
- `config_changed`: Run when the Juju config command is called and is used to pass configuration into the Charm. Due to how secrets work in Juju, this is also where secrets are passed in via the `env-vars` config value, which takes a url to the secret you with to pass in.

# Reference

## Configuration Values

The following configuration options are available on the Container Runner charm:

### `container-port`
- **Type**: `int`
- **Default**: `80`
- **Description**:  
  The internal port on which the application inside the container listens for web traffic.

### `host-port`
- **Type**: `int`
- **Default**: `80`
- **Description**:  
  The external port on the host machine that maps to the container's internal port, allowing access to the application from outside the container.

### `container-image-uri`
- **Type**: `string`
- **Default**: `nginxdemos/hello`
- **Description**:  
  The image or image URI that will be run by the container runner.

### `database-expected`
- **Type**: `boolean`
- **Default**: `false`
- **Description**:  
  A flag that determines if a database relation should be waited for before starting the container runner.

### `env-vars`
- **Type**: `secret`
- **Description**:  
  Expects the string content of a `.env` file, with each variable on a new line.

#  How-to guides
 
The following are a series of how-to's to guide you through managing and deploying a containerized application via the Container Runner charm.

## How to setup a development environment

The Juju team good documentation on how to setup a development environment which can be found [here](https://juju.is/docs/sdk/dev-setup). This should get you to a place where you have a virtual machine setup with the `juju` and `charmcraft` cli tools, as well as a bootstrapped Juju environment with a micro-k8s and lxd controller for deploying charms to.

A key thing to keep in mind is that the Container Runner charm is a machine charm, not a Kubernetes charm. The main consequence of this is that you will need to make sure you are targeting a lxd Juju controller when deploying locally, not a micro-k8s controller.

You can check which controller you Juju cli tool is targeting by running:
```
juju controllers
```

You will want to make sure the controller you are targeting has the Cloud/Region of `localhost/localhost`

You can switch the controller you are targeting by running:
```
juju switch <controller-name>
```
## How to build the Charm locally

Until the Container Runner charm is published to Charmhub, is will need to be built and deployed from the packed charm artifact. 

The Charm can be build via the Charmcraft snap. Charmcraft can be installed via:
```
sudo snap install charmcraft --classic
```

To pack the Container Runner charm, navigate to the project root and run:
```
charmcraft pack
```

This will produce a `.charm` artifact that can be installed on a Juju lxd controller.

## How to deploy a simple web application

The charm built in the previous step can be deployed using the `juju deploy` command.

```
juju deploy ./container-runner_ubuntu-22.04-amd64.charm --config container-image-uri=nginxdemos/hello --config host-port=80 --config container-port=80
```

There are a few key things to pull of of this command.
- You don't need to pass in command line arguments for all your configuration, and can instead pass in a yaml-formatted application config file.
- The path to the charm is prefaced with `./` to tell Juju the charm is available locally and not to search for it on charmhub.
- The `container-image-uri` will point the Docker snap to pull the `nginxdemos/hello` container from Dockerhub, which when curled returns a hello world response.
- The `host-port` and `container-port` config values are both set at 80
	- This will be passed along to the Docker snap when running the OCI image to [publish ports](https://docs.docker.com/get-started/docker-concepts/running-containers/publishing-ports/). (equivalent to `-p 80:80`)
	- Use the `host-port` to open a port for external traffic to the charm.

Running `juju status` will show the current states of the model. After a few minutes, the charm should be installed and setup. Our `container-runner` [app](https://juju.is/docs/juju/application) is deployed and active, and has a deployed and active [unit](https://juju.is/docs/juju/unit):

```
ubuntu@charm-dev-vm:~$ juju status
Model        Controller  Cloud/Region         Version  SLA          Timestamp
welcome-lxd  lxd         localhost/localhost  3.5.3    unsupported  14:46:03+02:00

App               Version  Status  Scale  Charm             Channel  Rev  Exposed  Message
container-runner           active      1  container-runner             2  no       

Unit                 Workload  Agent  Machine  Public address  Ports   Message
container-runner/2*  active    idle   71       10.191.96.77    80/tcp  

Machine  State    Address       Inst id         Base          AZ  Message
71       started  10.191.96.77  juju-994b56-71  ubuntu@22.04      Running
```

From here running curl against the public address of the active unit will respond with a relatively verbose hello world:
```
ubuntu@charm-dev-vm:~$ curl http://10.191.96.77:80
<!DOCTYPE html>
<html>
<head>
<title>Hello World</title>
...
```

## How to pass secrets into the running container

There are a few different types of secrets in Juju. The Container Runner charm makes use of a [user secret](https://juju.is/docs/juju/secret#heading--user) to pass secrets into a charm, and then into the container the charm is managing. 

> [!IMPORTANT]
> Secrets will be passed into the container as environment variables for the application within the container to read.

A consequence of secret life cycles in Juju requires the Container Runner charm to first be deployed before the secret can be passed in. This is because deployed applications must first be granted access to a secret before it can read it, and only a running application can be targeted for granting access to a secret. 

Lets say we want to pass the secrets `API_KEY=foo` and `JWT_TOKEN=bar` into our running container in an instance of the Container Runner.

>[!NOTE]
> Secrets can only be of type `string`. As the Container Runner charm needs to take in an arbitrary list of secrets to pass in through to the container, secrets need to be created with the name `env-vars` and the content of a valid `.env` file, including the new line formatting.

First [add the secret](https://juju.is/docs/juju/manage-secrets#heading--add-a-secret):
```
juju add-secret my-secret env-vars="API_KEY=foo
JWT_TOKEN=bar"
```

Juju will return the address of your newly created secret:
```
secret:crcqo7t17ppj98olptsg
```
 
 You can also view all available secrets by running:
```
 juju secrets
```

Once the secret is created and the charm is deployed, the charm can be granted access to the secret:
```
juju grant-secret my-secret container-runner
```

While this grants the charm access to view the secret, it does not pass the charm the secret. To do that update the charm's config with the address of the secret:
```
juju config container-runner env-vars=secret:crcqo7t17ppj98olptsg
```

## How to pass non-secret config into the running container

[Juju config values](https://juju.is/docs/juju/juju-config) need to be defined at charm compilation. As a result, they are not suitable for the Container Runner charm's use case of passing in arbitrary configuration to the running container.

To solve this, the Container Runner charm makes use of [Juju resources](https://juju.is/docs/juju/juju-resources) to provide the charm with a `.env` file that will be parsed and its values passed into the environment of the running container.

To deploy a charm with config provided by a Juju resource, first create a valid `.env` file. ie:
```env
LOG_LEVEL=info
ENV=dev
```
**TODO: how to obtain a resource from `charmhub.io`**

Then, when deploying the Container Runner charm, pass in a resource argument, specifying the `.env` file:
```
juju deploy ./container-runner_ubuntu-22.04-amd64.charm --resource env-file=/path/to/env-file.env
```

## How to connect to a database

Database connections are passed through to the running OCI image the `APP_POSTGRES_URI` environment variable. The application running in the container is restricted to receiving the connection string via this environment variable.

The connection string will come in the format:
`postgresql://{username}:{password}@{endpoints}/ratings`
**FIXME: generalize beyond ratings**

To trigger the event that will have this connection string passed into the running container, the Container Runner charm will need to be [related](https://juju.is/docs/juju/relation) to a postgresql charm.

```
juju relate postgresql container-runner
```

> [!NOTE]
> It is recommended to make use of the `database-expected` config value to indicate to the Container Runner charm to wait for a database relation before attempting to run the managed container.

