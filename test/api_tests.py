import dropbox
import os
import time
import simplejson
from urllib2 import urlopen

class SimpleDropbox(object):
    
    def __init__(self, oauth_token):
        self.client = dropbox.client.DropboxClient(oauth_token)
        self.tree_contents = {'/':{}}
        self.files = {
            '/foobar': {
                "name": 'foobar',
                "size": "0 bytes",
                "is_dir": True,
                "icon": "folder",
                "root": "dropbox" },
            '/testfile.txt': {
                "name": 'testfile.txt',
                "size": "0 bytes",
                "is_dir": False,
                "icon": "text",
                "root": "dropbox"
            }
        }

    def getClient(self):
        return self.client

    def getTreeContents(self):
        return self.tree_contents

    def getFilesList(self):
        return self.files

    def upload_file(self, filename):
        #uploads a file to Dropbox
        f = self.client.put_file("/", filename)
        return f

    def download_file(self, filepath):
        #downloads a file from Dropbox
        f = self.client.get_file(filepath)
        return f

    def create_dir(self, path):
        #creates a dir
        self.client.file_create_folder(path)

        # update tree_contents
        name = os.path.basename(path)
        if os.path.dirname(path) in self.tree_contents:
            self.tree_contents[os.path.dirname(path)][name] = \
                {'name': name, 'type': 'dir', 'size': 0, 'ctime': time.time(), 'mtime': time.time()}

        if path not in self.files:
            self.files[path] = {'path': path, 'is_dir': True, 'root': 'dropbox'}

    def remove_dir(self, path):
        #deletes a dir
        if path in self.files:
            del self.files[path]
        self.client.file_delete(path)

    def remove_file(self, path):
        #deletes a file/dir

        if path in self.files:
            del self.files[path]
        self.client.file_delete(path)

    def read_write_file(self, path):
        #reads & writes to file

        if path in self.files:
            del self.files[path]
        self.client.file_delete(path)

    def acc_info_request(self):
        resp = "client_info"
        response = urlopen(resp)
        raw_data = response.read().decode('utf-8')
        return simplejson.loads(raw_data)

    def file_metadata_request(self):
        resp = "metadata"
        response = urlopen(resp)
        raw_data = response.read().decode('utf-8')
        return simplejson.loads(raw_data)
        