#Michael Kemp - 6273632 - mkem114

#!/usr/bin/env python
from __future__ import print_function, absolute_import, division, with_statement
import os
import sys
import errno
import logging
from sys import argv, exit
from errno import ENOENT
from collections import defaultdict
from stat import S_IFDIR, S_IFLNK, S_IFREG
from time import time
from fuse import FUSE, FuseOSError, Operations, LoggingMixIn

if not hasattr(__builtins__, 'bytes'):
    bytes = str


class A2Fuse2(LoggingMixIn, Operations):
    def __init__(self, root):
        self.root = root
        self.files = {}
        self.data = defaultdict(bytes)
        self.fd = 0
        now = time()
        self.files['/'] = dict(st_mode=(S_IFDIR | 0o755), st_ctime=now,
                               st_mtime=now, st_atime=now, st_nlink=2)

    # Helpers
    # =======

    def _full_path(self, partial):
        if partial.startswith("/"):
            partial = partial[1:]
        path = os.path.join(self.root, partial)
        return path

    # Filesystem methods
    # ==================

    def access(self, path, mode):
        if path not in self.files:
            full_path = self._full_path(path)
            if not os.access(full_path, mode):
                raise FuseOSError(errno.EACCES)
        else:
            return 0

    def chmod(self, path, mode):
        if path not in self.files:
            full_path = self._full_path(path)
            return os.chmod(full_path, mode)
        else:
            self.files[path]['st_mode'] &= 0o770000
            self.files[path]['st_mode'] |= mode
            return 0

    def chown(self, path, uid, gid):
        if path not in self.files:
            full_path = self._full_path(path)
            return os.chown(full_path, uid, gid)
        else:
            self.files[path]['st_uid'] = uid
            self.files[path]['st_gid'] = gid

    def create(self, path, mode, fi=None):
        self.files[path] = dict(st_mode=(S_IFREG | mode), st_nlink=1, st_uid=os.getuid(), st_gid=os.getuid(),
                                st_size=0, st_ctime=time(), st_mtime=time(),
                                st_atime=time())

        self.fd += 1
        return self.fd

    def getattr(self, path, fh=None):
        if path not in self.files:
            full_path = self._full_path(path)
            st = os.lstat(full_path)
            return dict((key, getattr(st, key)) for key in ('st_atime', 'st_ctime',
                         'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size', 'st_uid'))
        else:
            if path not in self.files:
                raise FuseOSError(ENOENT)

            return self.files[path]

    def getxattr(self, path, name, position=0):
        if path in self.files:
            attrs = self.files[path].get('attrs', {})

            try:
                return attrs[name]
            except KeyError:
                return ''       # Should return ENOATTR
        else:
            return ''

    def listxattr(self, path):
        attrs = self.files[path].get('attrs', {})
        return attrs.keys()

    def mknod(self, path, mode, dev):
        return os.mknod(self._full_path(path), mode, dev)

    def mkdir(self, path, mode):
        if path not in self.files:
            return os.mkdir(self._full_path(path), mode)
        else:
            self.files[path] = dict(st_mode=(S_IFDIR | mode), st_nlink=2,
                                    st_size=0, st_ctime=time(), st_mtime=time(),
                                    st_atime=time())

            self.files['/']['st_nlink'] += 1

    def open(self, path, flags):
        if path not in self.files:
            full_path = self._full_path(path)
            return os.open(full_path, flags)
        else:
            self.fd += 1
            return self.fd

    def read(self, path, length, offset, fh):
        if path not in self.files:
            os.lseek(fh, offset, os.SEEK_SET)
            return os.read(fh, length)
        else:
            return self.data[path][offset:offset + length]

    def readdir(self, path, fh):
        dirents = ['.', '..']
        if path not in self.files:
            full_path = self._full_path(path)
            if os.path.isdir(full_path):
                dirents.extend(os.listdir(full_path))
        elif path == "/":
            full_path = self._full_path(path)
            if os.path.isdir(full_path):
                dirents.extend(os.listdir(full_path))
            dirents.extend([x[1:] for x in self.files if x != '/'])
        else:
            dirents.extend([x[1:] for x in self.files if x != '/'])
        for r in dirents:
            yield r

    def readlink(self, path):
        if path not in self.files:
            pathname = os.readlink(self._full_path(path))
            if pathname.startswith("/"):
                # Path name is absolute, sanitize it.
                return os.path.relpath(pathname, self.root)
            else:
                return pathname
        else:
            return self.data[path]

    def removexattr(self, path, name):
        attrs = self.files[path].get('attrs', {})

        try:
            del attrs[name]
        except KeyError:
            pass        # Should return ENOATTR

    def rename(self, old, new):
        if old not in self.files:
            self.files[new] = self.files.pop(old)
        else:
            return os.rename(self._full_path(old), self._full_path(new))

    def rmdir(self, path):
        if path not in self.files:
            full_path = self._full_path(path)
            return os.rmdir(full_path)
        else:
            self.files.pop(path)
            self.files['/']['st_nlink'] -= 1

    def setxattr(self, path, name, value, options, position=0):
        # Ignore options
        attrs = self.files[path].setdefault('attrs', {})
        attrs[name] = value

    def statfs(self, path):
        if path not in self.files:
            full_path = self._full_path(path)
            stv = os.statvfs(full_path)
            return dict((key, getattr(stv, key)) for key in ('f_bavail', 'f_bfree',
                'f_blocks', 'f_bsize', 'f_favail', 'f_ffree', 'f_files', 'f_flag',
                'f_frsize', 'f_namemax'))
        else:
            return dict(f_bsize=512, f_blocks=4096, f_bavail=2048)

    def symlink(self, name, target):
        if name not in self.files:
            return os.symlink(target, self._full_path(name))
        else:
            source = target
            target = name
            self.files[target] = dict(st_mode=(S_IFLNK | 0o777), st_nlink=1,
                                      st_size=len(source))

            self.data[target] = source

    def truncate(self, path, length, fh=None):
        if path not in self.files:
            full_path = self._full_path(path)
            with open(full_path, 'r+') as f:
                f.truncate(length)
        else:
            self.data[path] = self.data[path][:length]
            self.files[path]['st_size'] = length

    def unlink(self, path):
        if path not in self.files:
            return os.unlink(self._full_path(path))
        else:
            self.files.pop(path)

    def link(self, target, name):
        return os.link(self._full_path(name), self._full_path(target))

    def utimens(self, path, times=None):
        if path not in self.files:
            return os.utime(self._full_path(path), times)
        else:
            now = time()
            atime, mtime = times if times else (now, now)
            self.files[path]['st_atime'] = atime
            self.files[path]['st_mtime'] = mtime

    # def write(self, path, buf, offset, fh):
    def write(self, path, data, offset, fh):
        if path not in self.files:
            os.lseek(fh, offset, os.SEEK_SET)
            return os.write(fh, data)
        else:
            self.data[path] = self.data[path][:offset] + data
            self.files[path]['st_size'] = len(self.data[path])
            return len(data)

    # File methods
    # ============

    def flush(self, path, fh):
        if path not in self.files:
            return os.fsync(fh)
        else:
            return 0;

    def release(self, path, fh):
        if path not in self.files:
            return os.close(fh)
        else:
            return 0

    def fsync(self, path, fdatasync, fh):
        if path not in self.files:
            return self.flush(path, fh)
        else:
            return 0


def main(mountpoint, root):
    FUSE(A2Fuse2(root), mountpoint, nothreads=True, foreground=True)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main(sys.argv[2], sys.argv[1])