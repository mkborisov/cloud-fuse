import dropbox
import api_tests
import mock
import os
import tempfile
import unittest

"""
Mock up the actual API calls so that tests can be executed without 
connecting to the actual Dropbox API.
Purpose: Perform a set of unit tests
"""

def get_fake_response(resp):

    """A stub urlopen() implementation that loads json responses from
    the filesystem"""
    resource_file = os.path.normpath('responses/%s' %resp)    
    # return a file-like object
    return open(resource_file, mode='rb')

class DropboxTestCase(unittest.TestCase):

    @mock.patch('api_tests.urlopen', get_fake_response)
    def test_acc_info_request(self):

        # checks file upload without actually uploading the file
        client = api_tests.SimpleDropbox("fakeOauthToken")
        response = client.acc_info_request()
        self.assertIn('display_name', response)
        self.assertEqual(response['display_name'], 'Mario Borisov')

    @mock.patch('api_tests.urlopen', get_fake_response)
    def test_file_metadata_request(self):
        #Test a simple file metadata request
        client = api_tests.SimpleDropbox("fakeOauthToken")
        response = client.file_metadata_request()
        self.assertIn('path', response)
        self.assertIn('size', response)
        self.assertEqual(response['path'], "/test/testf1")
        self.assertEqual(response['size'], "20 bytes")
    
    @mock.patch.object(dropbox.client.DropboxClient, 'put_file', autospec=True)
    def test_upload_file(self, mock_put_object):

        # checks file upload without actually uploading the file
        client = api_tests.SimpleDropbox("fakeOauthToken")
        c = client.getClient()
        client.upload_file("somefile")
        # verify that put_file() was called with the right arguments
        mock_put_object.assert_called_with(c, "/", "somefile")

    def test_upload_response_params(self):

        client = api_tests.SimpleDropbox("fakeOauthToken")
        with mock.patch.object(dropbox.client.DropboxClient, 'put_file') as put_method:
            put_method.return_value = {'size':'', 'bytes':'', 'path':''}
            # verify that the call to put_file returns a dict with file attributes
            self.assertEqual(client.upload_file('testfile.html'), {'size':'','bytes':'','path':''})

    @mock.patch.object(dropbox.client.DropboxClient, 'get_file', autospec=True)
    def test_download_file(self, mock_get_object):

        # checks file download without actually downloading the file
        client = api_tests.SimpleDropbox("fakeOauthToken")
        c = client.getClient()
        client.download_file("somefile")
        # verify that get_file() was called with the right argument
        mock_get_object.assert_called_with(c, "somefile")

    def test_download_response_params(self):

        client = api_tests.SimpleDropbox("fakeOauthToken")
        with mock.patch.object(dropbox.client.DropboxClient, 'get_file') as get_method:
            with tempfile.NamedTemporaryFile() as f:
                get_method.return_value = f
                # verify that get_file() was called with the right argument
                self.assertEqual(client.download_file('testfile.html'), f)

    @mock.patch.object(dropbox.client.DropboxClient, 'file_create_folder', autospec=True)
    def test_create_dir(self, mock_create_object):

        # checks that we create a dir without actually creating the dir
        client = api_tests.SimpleDropbox("fakeOauthToken")
        c = client.getClient()
        client.create_dir("/somedir")
        dir_dict = client.getTreeContents()
        files_dict = client.getFilesList()
        # assert that file_create_folder() was called with the right arguments
        mock_create_object.assert_called_with(c, "/somedir")
        # assert dir is in files list
        self.assertEqual('somedir', dir_dict['/']['somedir']['name'])
        self.assertTrue('/somedir' in files_dict)

    @mock.patch.object(dropbox.client.DropboxClient, 'file_delete', autospec=True)
    def test_remove_dir(self, mock_delete_object):

        # checks that we delete a dir without actually deleting the dir
        client = api_tests.SimpleDropbox("fakeOauthToken")
        c = client.getClient()
        client.remove_dir("/somedir")
        files_dict = client.getFilesList()
        # assert that file_create_folder() was called with the right arguments
        mock_delete_object.assert_called_with(c, "/somedir")
        self.assertFalse('/somedir' in files_dict)

    @mock.patch.object(dropbox.client.DropboxClient, 'file_delete', autospec=True)
    def test_remove_file(self, mock_delete_object):

        # checks that we delete file without actually deleting file
        client = api_tests.SimpleDropbox("fakeOauthToken")
        c = client.getClient()
        client.remove_file("/testfile.txt")
        files_dict = client.getFilesList()
        # assert that file_create_folder() was called with the right arguments
        mock_delete_object.assert_called_with(c, "/testfile.txt")
        self.assertFalse('/testfile.txt' in files_dict)

if __name__ == '__main__':
    unittest.main()