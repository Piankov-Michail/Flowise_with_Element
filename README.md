# Flowise_with_Element
### <br>

## Infrastructure
```shell
docker network create matrix-network
```
<br>

## Synapse (server)
### Generete config
```shell
docker run -it --rm \
  -v synapse-data:/data \
  -e SYNAPSE_SERVER_NAME=localhost \
  -e SYNAPSE_REPORT_STATS=no \
  matrixdotorg/synapse:latest generate
```
### Launch service
```shell
docker run -d \
  --name synapse \
  --network matrix-network \
  -p 8008:8008 \
  -v synapse-data:/data \
  matrixdotorg/synapse:latest
  ```
<br>

## Flowise
```shell
docker run -d \
  --name flowise \
  --network matrix-network \
  -p 3000:3000 \
  -v flowise-data:/data \
  -e FLOWISE_USERNAME=admin \
  -e FLOWISE_PASSWORD=password \
  flowiseai/flowise:latest
  ```
<br>

## Make user for Element(Matrix)
```shell
docker exec -it synapse register_new_matrix_user http://localhost:8008 -c /data/homeserver.yaml
```
<br>

## Open [Element Web](https://app.element.io/) or download Element Desktop
### Choose Home server URL: http://localhost:8008
### Identity server URL: smth
<br>

## Configure Flowise (Example)
### Launch ollama with cloud model
```shell
docker run -d --network=matrix-network -v ollama:/root/.ollama --name ollama ollama/ollama
```
```shell
docker exec -it ollama ollama signin
```
```shell
docker exec -it ollama ollama run gpt-oss:20b-cloud
```
### Import this [Chatflow](https://github.com/Piankov-Michail/Flowise_with_Element/blob/main/Example_Chatflow.json)
<br>

## Launch [matrix-bot.py](https://github.com/Piankov-Michail/Flowise_with_Element/blob/main/matrix-bot.py)
### Make user for bot in Element(Matrix)
```
docker exec -it synapse register_new_matrix_user http://localhost:8008 -c /data/homeserver.yaml
```
### Maybe not in docker each student create this or auto docker with flowise_url and user_id from .env
```shell
python3 -m venv matrix-env
source matrix-env/bin/activate
pip install -r requirements.txt
```
```
python matrix-bot.py
```
<br>

## [DEMO](https://github.com/Piankov-Michail/Flowise_with_Element/blob/main/DEMO.pdf)
<br>

## Resources:
* [Synapse](https://github.com/matrix-org/synapse)
* [Flowise](https://github.com/FlowiseAI/Flowise)
