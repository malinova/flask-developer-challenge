# coding=utf-8
"""
Exposes a simple HTTP API to search a users Gists via a regular expression.

Github provides the Gist service as a pastebin analog for sharing code and
other develpment artifacts.  See http://gist.github.com for details.  This
module implements a Flask server exposing two endpoints: a simple ping
endpoint to verify the server is up and responding and a search endpoint
providing a search across all public Gists for a given Github account.
"""

import requests
import re
from flask import Flask, jsonify, request
from redis import Redis
import traceback
import os
import json

# *The* app object
app = Flask(__name__)

if os.environ.get("WITH_REDIS"):
    redis_client = Redis(host='cache', port=6379, decode_responses=True)
else:
    redis_client = None

class ExternalError(Exception):
    pass

class UserNotFound(Exception):
    pass

class BadOrMissingParameter(Exception):
    pass

@app.route("/ping")
def ping():
    """Provide a static response to a simple GET request."""
    return "pong"


def gists_for_user(username):
    """Provides the list of gist metadata for a given user.

    This abstracts the /users/:username/gist endpoint from the Github API.
    See https://developer.github.com/v3/gists/#list-a-users-gists for
    more information.

    Args:
        username (string): the user to query gists for

    Returns:
        The dict parsed from the json response from the Github API.  See
        the above URL for details of the expected structure.
    """

    # Github API limit per page (from the docs)
    per_page=100
    page=1
    gists_url = 'https://api.github.com/users/{username}/gists?per_page={per_page}&page={page}'.format(
            username=username, per_page=per_page, page=page)
    

    all_gists = []

    # BONUS: What failures could happen?
    try:
        response = requests.get(gists_url)
        response.raise_for_status()
        all_gists = response.json()

        # BONUS: Paging? How does this work for users with tons of gists?
        # The GitHub API does not return pagination information
        # so retrieve while there is still content
        # total limit is 3000 (GitHub API docs)
        while len(response.json()) == per_page and page <= 30:
            page += 1
            gists_url = 'https://api.github.com/users/{username}/gists?per_page={per_page}&page={page}'.format(
            username=username, per_page=per_page, page=page)
            response = requests.get(gists_url)
            response.raise_for_status()
            all_gists += response.json()
        
    except:
        traceback.print_exc()
        raise ExternalError()

    return all_gists

def fetch_file_content(raw_url):
    """ Fetches the text content of a single file from a Gist.

        If running in Docker and redis is available, check and use cache.
    """
    if redis_client:
        check_cache = redis_client.get(raw_url)
    else:
        check_cache = None
    
    if check_cache != None:
        return check_cache
    else:
        r = requests.get(raw_url)

        if redis_client:
            redis_client.set(raw_url, r.text)
        
        return r.text


def fetch_single_gist(url):
    """ Fetches the JSON content of a single Gist Object.

        If running in Docker and redis is available, check and use cache.
    """

    if redis_client:
        check_cache = redis_client.get(url)
    else:
        check_cache = None
    
    if check_cache != None:
        return json.loads(check_cache)
    else:
        r = requests.get(url)

        if redis_client:
            redis_client.set(url, json.dumps(r.json()))

        return r.json()

def check_user_exists(username):
    """ Check if a user exists.
        Raise error if user does not exist.
    """
    url = 'https://api.github.com/users/{username}'.format(username=username)
    r = requests.get(url)
    if r.status_code == 404:
        raise UserNotFound()

@app.route("/api/v1/search", methods=['POST'])
def search():
    """Provides matches for a single pattern across a single users gists.

    Pulls down a list of all gists for a given user and then searches
    each gist for a given regular expression.

    Returns:
        A Flask Response object of type application/json.  The result
        object contains the list of matches along with a 'status' key
        indicating any failure conditions.
    """
    try:
        post_data = request.get_json()

        # BONUS: Validate the arguments?
        if post_data['username']==None or post_data['pattern']==None:
            raise BadOrMissingParameter()

        username = post_data['username']
        pattern = post_data['pattern']

        try:
            re.compile(pattern)
        except:
            raise BadOrMissingParameter()

        result = {}

        # BONUS: Handle invalid users?
        check_user_exists(username)

        gists = gists_for_user(username)

        matching=[]
        for gist in gists:
            # REQUIRED: Fetch each gist and check for the pattern
            gist_full = fetch_single_gist(gist[u"url"])

            for filename in gist_full[u"files"].keys():
                file_object = gist_full[u'files'][filename]
                file_text=None

                # BONUS: What about huge gists?
                if file_object[u'truncated']:
                    file_text=fetch_file_content(file_object[u'raw_url'])
                else:
                    file_text=file_object[u"content"]

                match = re.match(pattern, file_text)
                if match:
                    matching.append('https://gist.github.com/{username}/{id}'.format(username=username, id=gist_full[u"id"]))
                    break


            # BONUS: Can we cache results in a datastore/db?
            # ===> see fetch_file_content() and fetch_single_gist()

        result['status'] = 'success'
        result['username'] = username
        result['pattern'] = pattern
        result['matches'] = matching
        return jsonify(result)
    
    # Simulate exception layer
    except UserNotFound:
        result['status'] = 'error'
        result['code'] = 400
        result['message'] = "Invalid username"
        return result, 400
    except BadOrMissingParameter:
        result['status'] = 'error'
        result['code'] = 400
        result['message'] = "Bad or missing parameter"
        return result, 400
    except ExternalError:
        result['status'] = 'error'
        result['code'] = 500
        result['message'] = "Information could not be retrieved from Github"
        return result, 500
    except:
        # Print stacktrace of other errors for debugging
        traceback.print_exc()
        result['status'] = 'error'
        result['code'] = 500
        result['message'] = "Your request could not be processed"
        return result, 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8000, threaded=True)
