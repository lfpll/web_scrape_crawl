import base64
import json
import os
import logging
from google.cloud import storage, pubsub_v1, error_reporting, logging as cloud_logging
from bs4 import BeautifulSoup
import requests

HEADERS = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux i686; rv:64.0) Gecko/20100101 Firefox/64.0'}


def download_html(message, context):
    """Receives a message object from pubsub, on the key 'data' it retrieves an url
        Download this url into the _IN_BUCKET or republish if it fails
        If same name let the gcloud trigger update handle

    Arguments:
            data {[base64 encoded string]} -- object json encoded with data:{file_path}
            context {[object]} -- [description]
    """ 
    # The bucket to store this html page
    _OUT_BUCKET = os.environ["OUTPUT_HTML_BUCKET"]
    # The topic of this function
    _THIS_FUNCTION_TOPIC = os.environ["THIS_TOPIC"]   
    # The topic that will be passed the json path
    _PARSE_FUNCTION_TOPIC = os.environ["OUTPUT_JSON_TOPIC"]

    # Instantiating log client
    LOG_CLIENT = cloud_logging.Client()
    HANDLER = LOG_CLIENT.get_default_handler()
    LOGGER = logging.getLogger('cloudLogger')
    LOGGER.setLevel(logging.INFO)
    LOGGER.addHandler(HANDLER)

    def __error_path(publisher, pub_obj_encoded, tries, url, error):
        """Function to handle possible errors on pagination

        Args:
            pub_obj_encoded ([dict]): [pubsub dict witn infos of the page and tries]
            tries ([int]): [number of tries that this page was tried]
            url ([str]): [url to be parsed for pagination]
        """
        if tries < 5:
            publisher.publish(_THIS_FUNCTION_TOPIC, pub_obj_encoded)
        else:
            raise Exception(
                "%s was already parsed 5 times, ended with %s page" % (url, error))
    try:
        error_client = error_reporting.Client() 
        # Getting the url of the pagination page
        data = base64.b64decode(message['data']).decode('utf-8')
        json_decoded = json.loads(data)
        url = json_decoded['url']

        # Out file name to gsbucket
        file_name = url.split('/')[-1].replace(':','_').replace(';','_')
        storage_client = storage.Client()
        bucket = storage_client.get_bucket(_OUT_BUCKET)
        blob = bucket.blob(file_name)
        blob.metadata = blob.metadata or {}
        blob.metadata['url'] = url
        # If blob exists let gcloud trigger update handle

        response = requests.get(url, headers=HEADERS)
        publisher = pubsub_v1.PublisherClient()

        # Adding number o tries
        tries = 0
        if 'tries' in json_decoded:
            tries = int(json_decoded['tries']) + 1

        # Object for failure maximum of tries
        pub_obj_encoded = json.dumps(
            {'url': url, 'tries': tries}).encode("utf-8")

        # If the status is not 200 the requestor was blocked send back

        if response.status_code != 200:
            __error_path(publisher, pub_obj_encoded, tries,
                         url, error=response.status_code)
        else:  
            soup = BeautifulSoup(response.content, 'lxml')
            # Special case where this website bad implemented http errors
            if soup.select('title')[0].text == 'Error 500':
                __error_path(publisher, pub_obj_encoded, tries, url, error=500)
                publisher.publish(_THIS_FUNCTION_TOPIC, url.encode('utf-8'))
            else:
                # Saving the html by the url name
                pub_obj_encoded = json.dumps(
                    {'file_path': file_name, 'url': url}).encode("utf-8")

                # Storing the blob
                blob.upload_from_string(response.text)

                # Publish path to be parsed and transformed to json if new
                publisher.publish(_PARSE_FUNCTION_TOPIC, pub_obj_encoded)
    except Exception as error:
        error_client.report_exception()
