import requests

API_URL = "http://localhost:3000/api/v1/vector/upsert/afd20ae6-ab1b-40b8-bc52-2db8b0672311"

# use form data to upload files
form_data = {
    "files": ('example*', open('example*', 'rb'))
}
body_data = {
    "chunkSize": 1,
    "chunkOverlap": 1,
    "separators": "example",
}

def query(form_data, body_data):
    response = requests.post(API_URL, files=form_data, data=body_data)
    return response.json()

output = query(form_data, body_data)
