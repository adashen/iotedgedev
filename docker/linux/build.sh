export VERSION=$1
docker build -f Dockerfile -t microsoft/iotedgedev:$1 -t microsoft/iotedgedev:$1-linux -t microsoft/iotedgedev:latest -t microsoft/iotedgedev:latest-linux .
