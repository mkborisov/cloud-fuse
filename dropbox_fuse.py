#!/usr/bin/env python

import os
import sys
import stat
import errno
import pprint
import time
import tempfile
import dropbox
from config import AppCredentials # the file where app_secret and app_key are stored

from threading import Lock
from datetime import datetime
from fuse import FUSE, FuseOSError, LoggingMixIn, fuse_get_context

class DropboxAPI():
    def __init__(self):
        self.rwlock = Lock()
        self.client = self.dropbox_request()
        self.tree_contents = {}

    def dropbox_request(self):

        app_access_token = 'dropbox_auth.conf'
        token_file = open(app_access_token)
        token_secret = token_file.read()
        token_file.close()

        if token_secret != '':
            client = dropbox.client.DropboxClient(str(token_secret))

        else:
            #log in and authenticate with dropbox
            flow = dropbox.client.DropboxOAuth2FlowNoRedirect(AppCredentials.app_key, AppCredentials.app_secret)
                        
            # Have the user sign in and authorize this token
            authorize_url = flow.start()
            print '1. Go to: ' + authorize_url
            print '2. Click "Allow" (you might have to log in first)'
            print '3. Copy the authorization code.'
            
            code = raw_input("Enter the authorization code here: ").strip()
            access_token, user_id = flow.finish(code)
            client = dropbox.client.DropboxClient(access_token)
            
            # write the access_token to file for reuse
            token_file = open(app_access_token,'w')
            token_file.write("%s" % (access_token))
            token_file.close()

        return client

    def get_account_info(self):

        #returns the account information, such as user's display name, quota, email, etc
        acc_info = self.client.account_info()
        pprint.PrettyPrinter(indent = 2).pprint(acc_info)

    def list_objects(self, path):

        response = self.client.metadata(path)
        
        if 'contents' not in response:
            raise FuseOSError(errno.EIO) # IO error

        # build tree
        self.tree_contents[path] = {}
        for child in response['contents']:
            # utf8 encoding will handle special characters
            name = str((os.path.basename(child['path'])).encode('utf8'))

            d = child['modified']
            # format date string
            d = d[5:-6]
            date_object = datetime.strptime(d, '%d %b %Y %H:%M:%S')
            # convert datetime object to Unix timestamp
            time_stamp = (date_object - datetime(1970,1,1)).total_seconds()

            ctime = int(time_stamp)
            if child['modified'] == '':
                mtime = ctime
            else:
                mtime = int(time_stamp)
            
            if child['is_dir'] == True:
                obj_type = 'dir'
            else:
                obj_type = 'file'

            self.tree_contents[path][name] = {'name': name, 'type': obj_type, \
                    'size': child['bytes'], 'ctime': ctime, 'mtime': mtime}

        return self.tree_contents[path]

class DropboxFUSE(LoggingMixIn):

    def __init__(self, mountpoint, logfile=None):
        self.dropbox_api = DropboxAPI()
        self.logfile = logfile
        self.files = {}
        self.full_path = ''
        self.mountpoint = mountpoint
        self.extensions = ['.class'] # list of restricted file extensions

    # Helper functions
    # ================

    def get_full_path(self, path):

        root_dir = os.getcwd()
        mnt_dir = os.path.join(root_dir, self.mountpoint)
        path = "%s%s" % (mnt_dir[:-1], path)
        return path

    def file_get(self, path, download=True):
        if path in self.files:
            print "file_get: %s is in self.files" % path
            return self.files[path]

        # Temp file stores all files in /tmp dir
        # f.name gives the name of temp file
        # generate temp file
        f = tempfile.NamedTemporaryFile()

        if download == True: # if download is true
            # get file from dropbox
            print "download=true ", f.name
            raw = self.dropbox_api.client.get_file(path)
            # Read data off the underlying socket
            # and write the bytes to temp file
            f.write(raw.read())
            raw.close() # Close the underlying socket
        else:
            # new file is created
            print "download=false ", f.name
            raw = ''
            # create empty temp file
            f.write(raw)

        # populate dict with objects read
        self.files[path] = {'object': f, 'modified': False}
        return self.files[path]

    def file_rename(self, oldFile, newFile):
        
        if oldFile in self.files:
            self.files[newFile] = self.files[oldFile] # update name of old file
            del self.files[oldFile] # delete old file

    def file_close(self, path): # file gets uploaded before its closed 
        if path in self.files:
            if self.files[path]['modified'] == True: #if file is altered
                self.file_upload(path)

            print "closing: " + path

            self.files[path]['object'].close()
            del self.files[path]

    def file_upload(self, path):

        print 'entered file upload'

        if path not in self.files:
            raise FuseOSError(errno.EIO) # IO error

        fileObject = self.file_get(path)
        if fileObject['modified'] == False:
            return True

        f = fileObject['object']

        # go to beginning of the file
        f.seek(0)
        # get the name of temp file
        tfName = f.name
        # open for writing before it gets uploaded to remote storage
        ff = open(tfName, "rw+")

        restrict = self.restrictFile(path)
        if restrict == False:
            # upload file object
            response = self.dropbox_api.client.put_file(path, ff, overwrite=True)
            print "uploaded: ", response
            # trap any errors
            if response['rev'] == []:
                raise FuseOSError(errno.EIO) # IO error
        else:
            print "file %s restricted for upload " % path
            #name = os.path.basename(path)
            #response = self.dropbox_api.tree_contents[os.path.dirname(path)][name]
            #ff.seek(0)
            #rf = open(tfName, "r+")
            #ff.write('hello')
            #print "rf: ", rf
            #rf.close()       

        fileObject['modified'] = False

    def create_directory(self, path):

        new_dir = self.dropbox_api.client.file_create_folder(path)
        if path not in self.files:
            self.files[path] = new_dir

    def object_delete(self, path):

        if path in self.files:
            del self.files[path] # delete object from dictionary


    def restrictFile(self, path):

        """restricts a file being synchronised based on its extension"""

        # get file name and file extension
        fileName, fileExtension = os.path.splitext(path)
        if fileExtension not in self.extensions:
            return False
        else:
            return True

    # Filesystem methods
    # ==================
    
    def statfs(self, path):

        """
        Returns information about the mounted file system
        512 bytes blocksize => 4 kb of data transferred per second
        4096 total data blocks in filesystem
        2048 of free blocks available to unprivileged user
        """
        return dict(f_bsize=512, f_blocks=4096, f_bavail=2048)

    def getattr(self, path, fh=None):

        """
        Defining this method is mandatory for a working filesystem
        Returns an object with the listed attributes
        The files and the associated data is stored as a Python dictionary
        """

        self.full_path = self.get_full_path(path)

        if path == '/':
            st = dict(st_mode=(stat.S_IFDIR | 0755), st_nlink=2)
            st['st_ctime'] = st['st_atime'] = st['st_mtime'] = time.time()
            st['st_uid'] = os.getuid()
            st['st_gid'] = os.getgid()
        else:
            name = str(os.path.basename(path))
            objects = self.dropbox_api.list_objects(os.path.dirname(path))

            if name not in objects:
                raise FuseOSError(errno.ENOENT) #No such file or directory
            elif objects[name]['type'] == 'file':
                st = dict(st_mode=(stat.S_IFREG | 0644), st_nlink=1, st_size=int(objects[name]['size']))
            else:
                st = dict(st_mode=(stat.S_IFDIR | 0755), st_nlink=2)

            st['st_ctime'] = st['st_atime'] = objects[name]['ctime']
            st['st_mtime'] = objects[name]['mtime']
            st['st_uid'] = os.getuid()
            st['st_gid'] = os.getgid()

        return st

    def readdir(self, path, fh):
        """
        Purpose: Give a listing for 'ls'
        path: String containing relative path to file
        Returns: Directory listing for 'ls' command
        """
        #print "readdir: " + path
        objects = self.dropbox_api.list_objects(path)

        listing = ['.', '..']
        for f in objects:
            listing.append(f)
        return listing

    def mkdir(self, path, mode):

        print "creating new directory %s" % path
        self.create_directory(path)

    def rmdir(self, path):

        print "removing directory %s" % path
        self.object_delete(path)
        self.dropbox_api.client.file_delete(path)

    def unlink(self, path):

    	"""
    	Should remove the filesystem object at path
        It may have any type except for directory
    	"""
    	print "removing file %s" % path
        self.object_delete(path)
        self.dropbox_api.client.file_delete(path)

    def rename(self, oldFile, newFile):
        
        print "renaming: " + oldFile + " to " + newFile
        self.file_rename(oldFile, newFile)
        self.dropbox_api.client.file_move(oldFile, newFile)

    # Not supported operations. The system doesn't fit within this model.
    
    def chmod(self, path, mode):
        
        raise FuseOSError(errno.EPERM) # Operation not permitted
        
    def chown(self, path, uid, gid):
        
        raise FuseOSError(errno.EPERM) # Operation not permitted

    def symlink(self, target, name):
        
        raise FuseOSError(errno.EPERM) # Operation not permitted

    def readlink(self, path):
        
        raise FuseOSError(errno.EPERM) # Operation not permitted

    # File methods
    # ============
        
    def open(self, path, flags):
        
        """
        Purpose: Open the file referred to by path
        path: String giving the path to the file to open
        flags: String giving Read/Write/Append Flags to apply to file
        Returns: Pointer to file
        """

        print "opening file %s" % path

        restrict = self.restrictFile(path)
        if restrict == False:
            self.file_get(path)
        else:
            os.open(self.full_path, flags)

        return 0

    def read(self, path, size, offset, fh):
    
        # returns bytes read
        print "reading file %s" % path
        f = self.file_get(path)['object']
        f.seek(offset)
        buf = f.read(size)
        return buf
    
    def write(self, path, buf, offset=0, fh=None):

        print "writing to file %s" % path
        fileObject = self.file_get(path) # get file object
        f = fileObject['object']
        f.seek(offset) # set the file's current position
        fileObject['modified'] = True # file is modified
        f.write(buf) # write a string to the file
        return len(buf) # return number of bytes written

    def truncate(self, path, length, fh=None):
        
        # shrink or extend the size of a file to the specified size
        print "truncate: " + path
        f = self.file_get(path)['object']
        f.truncate(length)

    def create(self, path, mode):
        
        print "create: " + path
        name = os.path.basename(path) # return file name
        restrict = self.restrictFile(path)

        print "self.full_path", self.full_path

        if name[0] != '.' and restrict == False:
            # check if the directory is in the current directory tree
            # if it is, add the new file with the proper name and path 
            if os.path.dirname(path) in self.dropbox_api.tree_contents:
                self.dropbox_api.tree_contents[os.path.dirname(path)][name] = {'name': name, \
                        'type': 'file', 'size': 0, 'ctime': time.time(), 'mtime': time.time()}
                print "tree_contents: ", self.dropbox_api.tree_contents[os.path.dirname(path)][name] 
            
            fileObject = self.file_get(path, download=False) # get file object
            f = fileObject['object']
            f.seek(0) # set the file's current position
            fileObject['modified'] = True # file is modified

            self.file_upload(path)

        elif name[0] != '.' and restrict == True:
            print "creating restricted file"
     
            #os.open(self.full_path, os.O_RDWR | os.O_CREAT)

        return 0

    def release(self, path, fh):

        print "release: " + path
        self.file_close(path)

    def flush(self, path, fh):
        print "flush: " + path
        if path in self.files:
            if self.files[path]['modified'] == True:
                self.file_upload(path)

    def fsync(self, path, datasync, fh):
        print "fsync: " + path
        if path in self.files:
            if self.files[path]['modified'] == True:
                self.file_upload(path)

def main(mountpoint):
    fuse = FUSE(DropboxFUSE(mountpoint), mountpoint, foreground=True)

if __name__ == '__main__':
    main(sys.argv[1])
