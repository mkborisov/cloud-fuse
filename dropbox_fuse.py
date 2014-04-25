#!/usr/bin/env python

import os
import sys
import stat
import errno
import pprint
import tempfile
import socket
import dropbox
from dropbox.rest import ErrorResponse
from config import AppCredentials # app_secret and app_key
from time import time
from threading import Lock
from datetime import datetime
from fuse import FUSE, FuseOSError, LoggingMixIn, fuse_get_context

class DropboxAPI():
    def __init__(self):
        self.rwlock = Lock()
        self.client = self.dropbox_request()
        self.tree_contents = {}
        self.tree_contents_cache = {}

    def dropbox_request(self):

        app_access_token = 'dropbox_auth.conf'
        token_file = open(app_access_token)
        token_secret = token_file.read()
        token_file.close()

        if token_secret != '':
            client = dropbox.client.DropboxClient(str(token_secret))
        else:
            #log in and authenticate with dropbox
            flow = dropbox.client.DropboxOAuth2FlowNoRedirect(AppCredentials.app_key, \
                                                            AppCredentials.app_secret)                       
            # Have the user sign in and authorize this token
            authorize_url = flow.start()
            print '1. Go to: ' + authorize_url
            print '2. Click "Allow" (you might have to log in first)'
            print '3. Copy the authorization code.'
            
            code = raw_input("Enter the authorization code here: ").strip()
            try:
                access_token, user_id = flow.finish(code)
            except ErrorResponse, e:
                print "Error %s: %s" % (e.status, e.error_msg)
                print
                self.dropbox_request()
                return

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

    def upload_f_perm(self):

        # if permissions file doesnt exist,
        # create it and upload to dropbox
        f = open('.f_perm.txt', 'a+')
        res = self.client.put_file('/.f_perm.txt', f, overwrite=True)
        f.close()

    def search(self, values, searchFor):

        # search for specific path in metadata dict
        for k in values['contents']:
            if searchFor in k['path']:
                return True
        return False

    def list_objects(self, path, ttl=10):

        # for efficiency, store last snapshot of files in memory
        # this prevents calling metadata() constantly
        if path in self.tree_contents_cache:
            if self.tree_contents_cache[path] >= time():
                return self.tree_contents[path]

        # check if dropbox api host is accessible
        try:
            host = socket.getaddrinfo('api.dropbox.com', 443)
        except socket.gaierror, err:
            print "Cannot resolve hostname: ", 'api.dropbox.com', err

        try:
            # obtain file/folder metadata from dropbox
            response = self.client.metadata(path)
        except ErrorResponse, e:
            print "Error %s: %s" % (e.status, e.error_msg)

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

        db_api = DropboxAPI()
        #Check if permissions file exists locally & on dropbox
        is_existent = db_api.search(response, '/.f_perm.txt')
        
        if not is_existent:
            db_api.upload_f_perm() 
        elif not os.path.isfile('.f_perm.txt'):
            f = open('.f_perm.txt', 'a+')
            try:
                perm = self.client.get_file('/.f_perm.txt')
                perm_contents = perm.read()
                perm.close()
            except ErrorResponse, e:
                print "Error %s: %s" % (e.status, e.error_msg)
            lines = perm_contents.split('\n')
            for i in range(len(lines)-1):
                line = lines[i]
                f.write("%s\n" % (line))
            f.close()

        # update expiration time
        self.tree_contents_cache[path] = time() + ttl
        return self.tree_contents[path]

class DropboxFUSE(LoggingMixIn):

    def __init__(self, mountpoint, restr_dir):
        self.dropbox_api = DropboxAPI()
        self.files = {}
        self.mountpoint = mountpoint
        self.restr_dir = restr_dir
        self.restr_files = {}
        self.extensions = ['.ascii', '.class', '.log'] # restricted file extensions

    # Helper functions
    # ================

    def create_restr_dir(self):

        # this is where local restricted files will be stored
        root_dir = os.getcwd()
        restr_dir = os.path.join(root_dir, self.restr_dir)

        if not os.path.exists(restr_dir):
            os.mkdir(restr_dir, 0755)

    def get_restr_path(self, path):

        name = os.path.basename(path)
        root_dir = os.getcwd()
        restr_file = os.path.join(self.restr_dir, name)
        restr_path = os.path.join(root_dir, restr_file)
        return restr_path

    """
    def get_full_path(self, path):

        root_dir = os.getcwd()
        mnt_dir = os.path.join(root_dir, self.mountpoint)
        path = "%s%s" % (mnt_dir[:-1], path)
        return path
    """

    def file_get(self, path, download=True): 

        if path in self.restr_files:
            print "file_get: %s is in self.restr_files" % path
            return self.restr_files[path]

        if path in self.files:
            print "file_get: %s is in self.files" % path
            return self.files[path]
        
        # tempfile stores all files in /tmp
        # generate temp file
        f = tempfile.NamedTemporaryFile()

        if download == True:
            # get file from dropbox
            try:
                raw = self.dropbox_api.client.get_file(path)
                # Read data off the underlying socket
                # and write the bytes to temp file
                f.write(raw.read())
                raw.close() # Close the underlying socket
            except ErrorResponse, e:
                print "Error %s: %s" % (e.status, e.error_msg)
        
        elif download == None:
            # create or edit restricted file
            f_descr = os.open(path, os.O_RDWR|os.O_CREAT, 0664)

            # populate dict with restricted file descriptor
            self.restr_files[path] = {'file_descriptor': f_descr}                
            return self.restr_files[path]

        else:
            raw = ''
            # create empty temp file
            f.write(raw)

        # populate dict with file object
        self.files[path] = {'object': f, 'modified': False}
        return self.files[path]

    def file_rename(self, oldFile, newFile):
        
        if oldFile in self.files:
            self.files[newFile] = self.files[oldFile] # update name of old file
            del self.files[oldFile] # delete old file

        if oldFile in self.restr_files:
            self.restr_files[newFile] = self.restr_files[oldFile]
            del self.restr_files[oldFile]

    def file_close(self, path): # file gets uploaded before its closed

        if path in self.files:
            if self.files[path]['modified'] == True: #if file is altered
                self.file_upload(path)

            print "closing: " + path

            self.files[path]['object'].close()
            del self.files[path]

    def file_upload(self, path):

        print 'file upload %s' % path
        
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

        # upload file object
        try:
            response = self.dropbox_api.client.put_file(path, ff, overwrite=True)
        except ErrorResponse, e:
            print "Upload Error %s: %s" % (e.status, e.error_msg)

        print "uploaded: ", response
        # trap any errors
        if response['rev'] == []:
            raise FuseOSError(errno.EIO) # IO error

        ff.close() # close the file that got uploaded
        fileObject['modified'] = False
            
    def create_directory(self, path):

        try:
            new_dir = self.dropbox_api.client.file_create_folder(path)
        except ErrorResponse, e:
            print "Error %s: %s" % (e.status, e.error_msg)

        # update tree_contents
        name = os.path.basename(path)
        self.dropbox_api.tree_contents[os.path.dirname(path)][name] = \
            {'name': name, 'type': 'dir', 'size': 0, 'ctime': time(), 'mtime': time()}

        if path not in self.files:
            self.files[path] = new_dir

    def object_delete(self, path):

        if path in self.files:
            del self.files[path] # delete object from dictionary

    def restrictFile(self, path):

        # distinguish between dropbox file and local "restricted" file
        # stops a file being synchronised based on its extension

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
        Returns a stat() structure
        The files and the associated data is stored as a dictionary
        """
        
        # get fuse context
        (uid, gid, pid) = fuse_get_context()

        stat_result = { "st_mtime": time(), # modified time
                        "st_ctime": time(), # changed time
                        "st_atime": time(), # last access time
                        "st_uid": uid,      # user id
                        "st_gid": gid }     # group id

        if path == '/':
            #stat_result["st_size"] = 1024 * 4 # default size should be 4K
            stat_result['st_mode'] = (stat.S_IFDIR | 0755)
            stat_result['st_nlink'] = 2

        else:

            name = str(os.path.basename(path))
            # if a restricted file at restr_path, retrieve its metadata
            if name[name.rfind('.'):] in self.extensions:

                restr_path = self.get_restr_path(path)
                st = os.lstat(restr_path)

                return dict((key, getattr(st, key)) for key in ('st_atime', 'st_ctime',
                     'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size', 'st_uid'))

            # get files and directories metadata from dropbox
            objects = self.dropbox_api.list_objects(os.path.dirname(path))

            if name not in objects:
                raise FuseOSError(errno.ENOENT) # no such file or directory

            elif objects[name]['type'] == 'file':
                stat_result['st_size'] = int(objects[name]['size'])

                if path not in open('.f_perm.txt').read():
                    # file gets default permission
                    stat_result['st_mode'] = (stat.S_IFREG | 0644)
                else:
                    # file gets permission bits from f_perm file
                    with open('.f_perm.txt', 'r') as f: 
                        lines = f.readlines()
                    for line in lines:
                        p = line.split()[0]
                        if p == path:
                            stat_result['st_mode'] = int(line.split()[1])

                stat_result['st_nlink'] = 1
            else:
                # theres an issue with dropbox metadata api call
                # it always returns 0 bytes for folder size
                #stat_result["st_size"] = int(objects[name]['size'])
                stat_result['st_mode'] = (stat.S_IFDIR | 0755)
                stat_result['st_nlink'] = 2

            stat_result['st_ctime'] = stat_result['st_atime'] = objects[name]['ctime']
            stat_result['st_mtime'] = objects[name]['mtime']

        return stat_result


    def readdir(self, path, fh):
        """
        Purpose: Give a listing for 'ls'
        path: String containing relative path to file
        Returns: Directory listing for 'ls' command
        """
        #print "readdir: " + path

        restr_path = self.get_restr_path(path)
        restr_objects = []

        objects = self.dropbox_api.list_objects(path)
        if os.path.isdir(restr_path):
            restr_objects = os.listdir(restr_path)

        listing = ['.', '..']
        for f in objects:
            listing.append(f)

        for f in restr_objects:
            listing.append(f)

        return listing

    def mkdir(self, path, mode):

        print "creating new directory %s" % path
        self.create_directory(path)

    def rmdir(self, path):

        print "removing directory %s" % path
        self.object_delete(path)
        try:
            self.dropbox_api.client.file_delete(path)
        except ErrorResponse, e:
            print "Error %s: %s" % (e.status, e.error_msg)

    def unlink(self, path):

    	"""
    	Should remove the filesystem object at path
        It may have any type except for directory
    	"""

        restrict = self.restrictFile(path)
        
        if restrict == False:
            print "removing file %s" % path
            self.object_delete(path)
            try:
                self.dropbox_api.client.file_delete(path)
            except ErrorResponse, e:
                print "Error %s: %s" % (e.status, e.error_msg)
        
        else:
            restr_path = self.get_restr_path(path)
            print "removing file %s" % restr_path
            os.unlink(restr_path)

    def rename(self, oldFile, newFile):
        
        restrict = self.restrictFile(oldFile)

        if restrict == False:
            print "renaming: " + oldFile + " to " + newFile
            self.file_rename(oldFile, newFile)
            try:
                self.dropbox_api.client.file_move(oldFile, newFile)
            except ErrorResponse, e:
                print "Error %s: %s" % (e.status, e.error_msg)

        else:
            old_file = self.get_restr_path(oldFile)
            restr_dir = os.path.join(os.getcwd(), self.restr_dir)
            new_file = os.path.join(restr_dir, newFile[1:])
            print "renaming: " + old_file + " to " + new_file
            self.file_rename(old_file, new_file)
            os.rename(old_file, new_file)

    def chmod(self, path, mode):
        
        # change the access mode of a file
        restrict = self.restrictFile(path)

        if restrict == False:
            # handle permissions for dropbox files
            st_mode = (stat.S_IFREG | mode)
            # get octal value for file current permission
            st_mode_oct = oct(st_mode & 0777)

            try:
                perm = self.dropbox_api.client.get_file('/.f_perm.txt')
                perm_contents = perm.read()
                perm.close()
            except ErrorResponse, e:
                print "Error %s: %s" % (e.status, e.error_msg)

            if not os.path.isfile('.f_perm.txt') and perm_contents == '':
                f_perm = open('.f_perm.txt', 'a+')
                f_perm.close()

            elif not os.path.isfile('.f_perm.txt') and perm_contents != '':
                f_perm = open('.f_perm.txt', 'a+')
                lines = perm_contents.split('\n')
                for i in range(len(lines)-1):
                    line = lines[i]
                    f_perm.write("%s\n" % (line))
                    f_perm.close()

            else:
                f_perm = open('.f_perm.txt', 'a+')
                if path not in open('.f_perm.txt').read():
                    # if not default permission (0644), add new entry
                    if st_mode != 33188:
                        f_perm.write("%s    %s    %s\n" % (path, st_mode, st_mode_oct))
                        f_perm.close()
                        self.dropbox_api.upload_f_perm()

                else:
                    # remove the entry & write fresh value
                    lines = f_perm.readlines()
                    f_perm.close()
                    with open('.f_perm.txt', 'w') as f:
                        for line in lines:
                            p = line.split()[0]
                            if p != path:
                                f.write(line)
                        f.write("%s    %s    %s\n" % (path, st_mode, st_mode_oct))
                    self.dropbox_api.upload_f_perm()

        else:
            # restricted file
            restr_path = self.get_restr_path(path)
            return os.chmod(restr_path, mode) 


    """ Not supported operations. The system doesn't fit within this model """
        
    def chown(self, path, uid, gid):
        # change the owner of a file or directory
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

        restrict = self.restrictFile(path)

        if restrict == False:
            print "opening file %s" % path
            self.file_get(path)
        else:
            restr_path = self.get_restr_path(path)
            print "opening file %s" % restr_path
            self.file_get(restr_path, download=None)

        return 0

    def read(self, path, size, offset, fh):
        
        # returns bytes read
        restrict = self.restrictFile(path)

        if restrict == False:
            print "reading file %s" % path
            f = self.file_get(path)['object']
            f.seek(offset)
            buf = f.read(size)
            return buf
        else:
            restr_path = self.get_restr_path(path)
            print "reading file %s" % restr_path
            fid = self.file_get(restr_path, download=None)['file_descriptor']
            os.lseek(fid, offset, os.SEEK_SET)
            return os.read(fid, size)

    def write(self, path, buf, offset, fh):

        restrict = self.restrictFile(path)

        if restrict == False:
            print "writing to file %s" % path
            fileObject = self.file_get(path) # get file object
            f = fileObject['object']
            f.seek(offset) # set the file's current position
            fileObject['modified'] = True # file is modified
            f.write(buf) # write a string to the file
            return len(buf) # return number of bytes written
        else:
            restr_path = self.get_restr_path(path)
            print "writing to file %s" % restr_path
            fid = self.file_get(restr_path, download=None)['file_descriptor']
            os.lseek(fid, offset, os.SEEK_SET)
            return os.write(fid, buf)

    def truncate(self, path, length, fh=None):
        
        # shrink or extend the size of a file to the specified size
        restrict = self.restrictFile(path)

        if restrict == False:
            print "truncate: " + path
            f = self.file_get(path)['object']
            f.truncate(length)
        else:
            restr_path = self.get_restr_path(path)
            print "truncate: " + restr_path
            fid = self.file_get(restr_path, download=None)['file_descriptor']
            os.ftruncate(fid, length)

    def create(self, path, mode):
        
        name = os.path.basename(path) # return file name
        restrict = self.restrictFile(path)

        # handle vim .swp and [filename]~ files
        # dont create and upload those
        if name[0] != '.' and name != '4913' and name[-1:] != '~' and restrict == False:

            print "create: " + path
            # check if the directory is in the current directory tree
            # if it is, add the new file with the proper name and path 
            if os.path.dirname(path) in self.dropbox_api.tree_contents:
                self.dropbox_api.tree_contents[os.path.dirname(path)][name] = {'name': name, \
                        'type': 'file', 'size': 0, 'ctime': time(), 'mtime': time()}
                print "tree_contents: ", self.dropbox_api.tree_contents[os.path.dirname(path)][name] 
            
            fileObject = self.file_get(path, download=False) # get file object
            f = fileObject['object']
            f.seek(0) # set the file's current position
            fileObject['modified'] = True # file is modified

            self.file_upload(path)

        elif name[0] != '.' and restrict == True:

            # create dir where restricted file will be saved
            self.create_restr_dir()
            print "creating restricted file %s" % path

            restr_path = self.get_restr_path(path)
            print "create: " + restr_path
            fileObject = self.file_get(restr_path, download=None)

        return 0

    def release(self, path, fh):

        restrict = self.restrictFile(path)

        if restrict == False:
            print "release: " + path
            self.file_close(path)
        else:
            restr_path = self.get_restr_path(path)
            print "release: " + restr_path
            fid = self.file_get(restr_path, download=None)['file_descriptor']
            del self.restr_files[restr_path]
            os.close(fid)

    def flush(self, path, fh):

        # called on each close
        restrict = self.restrictFile(path)

        if restrict == False:
            print "flush: " + path
            if path in self.files:
                if self.files[path]['modified'] == True:
                    self.file_upload(path)
        else:
            restr_path = self.get_restr_path(path)
            print "flush: " + restr_path
            fid = self.file_get(restr_path, download=None)['file_descriptor']
            os.fsync(fid)

    def fsync(self, path, datasync, fh):
        
        # flush any dirty information about the file to disk
        restrict = self.restrictFile(path)

        if restrict == False:
            print "fsync: " + path
            if path in self.files:
                if self.files[path]['modified'] == True:
                    self.file_upload(path)
        else:
            restr_path = self.get_restr_path(path)
            print "fsync: " + restr_path
            fid = self.file_get(restr_path, download=None)['file_descriptor']
            self.flush(restr_path, fid)

def main(mountpoint, restr_dir):

    fuse = FUSE(DropboxFUSE(mountpoint, restr_dir), \
            mountpoint, noatime=True, foreground=True)

if __name__ == '__main__':

    if len(sys.argv) != 3:
        print "Wrong number of parameters."
        print "Usage: dropbox_fuse.py <mount_point> <restr_dir>"
        exit()

    main(sys.argv[1], sys.argv[2])
