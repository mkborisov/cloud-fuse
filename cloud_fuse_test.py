#!/usr/bin/env python

# Integration tests for cloud_fuse.py

from cloud_fuse import DropboxFUSE
import os
import stat
import errno
from pytest import raises
from fuse import FuseOSError

MNT_POINT = '/home/mario/CloudFUSE/FYP/bar/'
RESTR_DIR = '/home/mario/CloudFUSE/FYP/foo/'
FS = DropboxFUSE(MNT_POINT, RESTR_DIR)

# The following tests communicate across the network and use Dropbox API
# Purpose: Perform integration tests of the code to Dropbox API

def test_root_dir():

    # testing basic root dir properties
    attr = FS.getattr("/")
    assert stat.S_ISDIR(attr['st_mode'])
    assert attr['st_nlink'] == 2
    directory = list(FS.readdir("/"))
    assert '.' in directory
    assert '..' in directory

def test_file():
    
    # testing basic file properties 
    FS.create("/TEST/testfile", os.O_CREAT)
    assert "testfile" in FS.readdir("/TEST")
    attr = FS.getattr("/TEST/testfile")
    assert stat.S_ISREG(attr['st_mode'])
    FS.unlink("/TEST/testfile")
    assert not "testfile" in FS.readdir("/TEST")

def test_readwrite():

    # testing file read & write
    # write to file, read it back and check if its contents
    # equal to what was written to it
    msg = "Hello World!"
    FS.create("/TEST/testfile", os.O_CREAT)
    FS.write("/TEST/testfile", msg, 0)
    FS.fsync("/TEST/testfile", 0)
    msg2 = FS.read("/TEST/testfile", len(msg), 0)
    assert msg == msg2, (msg, msg2)
    FS.unlink("/TEST/testfile")

def test_file_size():

    # testing file size attribute
    msg = "some random teext..."
    FS.create("/TEST/testf1", os.O_CREAT)
    attr = FS.getattr("/TEST/testf1")
    assert attr['st_size'] == 0, attr['st_size']
    FS.write("/TEST/testf1", msg, 0)
    FS.fsync("/TEST/testf1", 0)
    attr = FS.getattr("/TEST/testf1")
    assert attr['st_size'] == len(msg), (attr['st_size'], len(msg))

def test_rename():

    # testing dir and file rename
    FS.mkdir("/TEST/test", 0644)
    FS.rename("/TEST/test", "/TEST/dir")
    assert "dir" in FS.readdir("/TEST")
    assert not "test" in FS.readdir("/TEST")
    FS.getattr("/TEST/dir")
    FS.create("/TEST/dir/hello.txt", os.O_CREAT)
    assert "hello.txt" in FS.readdir("/TEST/dir")
    FS.rename("/TEST/dir/hello.txt", "/TEST/dir/goodbye.txt")
    assert "goodbye.txt" in FS.readdir("/TEST/dir")
    assert not "hello.txt" in FS.readdir("/TEST/dir")
    # test for renaming in place
    with raises(FuseOSError) as excinfo:
        FS.rename("/TEST/dir/goodbye.txt", "/TEST/dir/goodbye.txt")
    assert 'File exists' in excinfo.value

def test_mkdir():

    # testing mkdir
    FS.mkdir("/TEST/bar", 0644)
    FS.mkdir("/TEST/bar/dir", 0644)
    FS.mkdir("/TEST/bar/dir2", 0644)
    assert "bar" in FS.readdir("/TEST")
    assert "dir" in FS.readdir("/TEST/bar")
    assert "dir2" in FS.readdir("/TEST/bar")

def test_double_mkdir():

    with raises(FuseOSError) as excinfo:
        FS.mkdir("/TEST/bubble", 0644)
        FS.mkdir("/TEST/bubble", 0644)
    assert 'File exists' in excinfo.value

def test_deletion():

    # testing file deletion
    FS.mkdir("/TEST/data", 0644)
    assert "data" in FS.readdir("/TEST")
    FS.unlink("/TEST/data")
    assert not "data" in FS.readdir("/TEST")

def test_noexists_rmdir():

    with raises(FuseOSError) as excinfo:
        FS.rmdir("/TEST/testdata")
    assert 'No such file or directory' in excinfo.value

def test_noexists_getattr():

    # get attributes of non existent file
    with raises(FuseOSError) as excinfo:
        FS.getattr("/TEST/mickey")
    assert 'No such file or directory' in excinfo.value

def test_noexists_remove():

    # remove non existent file
    with raises(FuseOSError) as excinfo:
        FS.unlink("/TEST/mickey")
    assert 'No such file or directory' in excinfo.value

def test_noexists_rename():

    # rename non existent file
    with raises(FuseOSError) as excinfo:
        FS.rename("/TEST/mickey", "/TEST/mickey_mouse")
    assert 'No such file or directory' in excinfo.value

def test_noexists_write():

    # writing to non existent file
    msg = "Hello World!"
    with raises(FuseOSError) as excinfo:
        FS.write("/TEST/mickey", msg, 0)
    assert 'No such file or directory' in excinfo.value

def test_noexists_read():

    # read non existent file
    with raises(FuseOSError) as excinfo:
        FS.read("/TEST/mickey", 10, 0)
    assert 'No such file or directory' in excinfo.value

def test_noexists_truncate():

    # truncate non existent file
    with raises(FuseOSError) as excinfo:
        FS.truncate("/TEST/mickey", 10)
    assert 'No such file or directory' in excinfo.value


