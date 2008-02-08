
from c3errors import *
from configParser import C3Object
import os, md5, sha, time
from baseObjects import Session
from random import Random
from dateutil import parser as dateparser

import string
try:
    from Ft.Lib.Uuid import GenerateUuid, UuidAsString
    use4Suite = 1
except:
    use4Suite = 0

randomGen = Random(time.time())
asciiChars = string.ascii_letters + string.digits + "@%#!-=."

import datetime, dateutil.tz

try:
    # name when installed by hand
    import bsddb3 as bdb
except:
    # name that comes in python 2.3
    import bsddb as bdb


class DeletedObject(object):
    id = ""
    time = ""
    store = ""
    
    def __nonzero__(self):
        return False

    def __init__(self, store, id, time="dunno when"):
        self.store = store
        self.id = id
        self.time = time

        
class SummaryObject(object):
    """ Allow database to have summary, but no storage """

    totalItems = 0
    totalWordCount = 0
    minWordCount = 0
    maxWordCount = 0
    meanWordCount = 0
    totalByteCount = 0
    minByteCount = 0
    maxByteCount = 0
    meanByteCount = 0
    lastModified = ''

    _possiblePaths = {'metadataPath' : {'docs' : "Path to file where the summary metadata will be kept."}}

    def __init__(self, session, config, parent):

        # don't want to inherit from database!
        mp = self.paths.get('metadataPath', '')
        if not mp:
            self.paths['metadataPath'] = ''
            return
        if (not os.path.isabs(mp)):
            # Prepend defaultPath from parents
            dfp = self.get_path(session, 'defaultPath')
            if (not dfp):
                raise(ConfigFileException("Store has relative metadata path, and no visible defaultPath."))
            mp = os.path.join(dfp, mp)
        self.paths['metadataPath'] = mp

        if (not os.path.exists(mp)):
            # We don't exist, try and instantiate new database
            self._initialise(mp)
        else:
            cxn = bdb.db.DB()
            try:
                cxn.open(mp)
                # Now load values.
                
                self.totalItems = long(cxn.get("totalItems"))
                self.totalWordCount = long(cxn.get("totalWordCount"))
                self.minWordCount = long(cxn.get("minWordCount"))
                self.maxWordCount = long(cxn.get("maxWordCount"))

                self.totalByteCount = long(cxn.get("totalByteCount"))
                self.minByteCount = long(cxn.get("minByteCount"))
                self.maxByteCount = long(cxn.get("maxByteCount"))
                
                self.lastModified = str(cxn.get("lastModified"))

                if self.totalItems != 0:
                    self.meanWordCount = self.totalWordCount / self.totalItems
                    self.meanByteCount = self.totalByteCount / self.totalItems
                else:
                    self.meanWordCount = 1
                    self.meanByteCount = 1
                cxn.close()
            except:
                # Doesn't exist in usable form
                self._initialise(mp)

    def _initDb(self, session, dbt):
            dbp = dbt + "Path"
            databasePath = self.get_path(session, dbp, "")
            if (not databasePath):
                databasePath = ''.join([self.id, "_", dbt, ".bdb"])
            if (not os.path.isabs(databasePath)):
                # Prepend defaultPath from parents
                dfp = self.get_path(session, 'defaultPath')
                if (not dfp):
                    raise(ConfigFileException("Store has relative path, and no visible defaultPath."))
                databasePath = os.path.join(dfp, databasePath)
            self.paths[dbp] = databasePath
                    
    def _initialise(self, dbPath):
        cxn = bdb.db.DB()
        cxn.set_flags(bdb.db.DB_RECNUM)
        try:
            cxn.open(dbPath, dbtype=bdb.db.DB_BTREE, flags = bdb.db.DB_CREATE, mode=0660)
        except:
            raise ValueError("Could not create %s" % dbPath)
        cxn.put("lastModified", time.strftime('%Y-%m-%d %H:%M:%S'))
        cxn.close()

    def commit_metadata(self, session):
        cxn = bdb.db.DB()
        mp = self.get_path(session, 'metadataPath')
        if mp:
            try:
                self.meanWordCount = self.totalWordCount / self.totalItems
                self.meanByteCount = self.totalByteCount / self.totalItems
            except ZeroDivisionError:
                self.meanWordCount = 1
                self.meanByteCount = 1
                
            self.lastModified = time.strftime('%Y-%m-%d %H:%M:%S')
            try:
                cxn.open(mp)
                cxn.put("totalItems", str(self.totalItems))
                cxn.put("totalWordCount", str(self.totalWordCount))
                cxn.put("minWordCount", str(self.minWordCount))
                cxn.put("maxWordCount", str(self.maxWordCount))
                cxn.put("totalByteCount", str(self.totalByteCount))
                cxn.put("minByteCount", str(self.minByteCount))
                cxn.put("maxByteCount", str(self.maxByteCount))
                cxn.put("lastModified", self.lastModified)
                cxn.close()
            except:
                # TODO: Nicer failure?
                raise

    def accumulate_metadata(self, session, obj):
        self.totalItems += 1
        self.totalWordCount += obj.wordCount
        if obj.wordCount < self.minWordCount:
            self.minWordCount = obj.wordCount
        if obj.wordCount > self.maxWordCount:
            self.maxWordCount = obj.wordCount

        self.totalByteCount += obj.byteCount
        if obj.byteCount < self.minByteCount:
            self.minByteCount = obj.byteCount
        if obj.byteCount > self.maxByteCount:
            self.maxByteCount = obj.byteCount
        
    

class SimpleStore(C3Object, SummaryObject):
    """ Base Store implementation.  Provides non-storage-specific functions """
    
    # Instantiate some type of simple record store
    idNormalizer = None
    outIdNormalizer = None
    inWorkflow = None
    outWorkflow = None
    storageTypes = []
    reverseMetadataTypes = []
    currentId = -1
    useUUID = 0

    _possiblePaths = {'idNormalizer' : {'docs' : "Identifier for Normalizer to use to turn the data object's identifier into a suitable form for storing. Eg: StringIntNormalizer"},
                      'outIdNormalizer' : {'docs' : "Normalizer to reverse the process done by idNormalizer"},
                      'inWorkflow' : {'docs' : "Workflow with which to process incoming data objects."},
                      'outWorkflow' : {'docs' : "Workflow with which to process stored data objects when requested."}
                      }

    _possibleSettings = {'useUUID' : {'docs' : "Each stored data object should be assigned a UUID.", 'type': int, 'options' : "0|1"},
                         'digest' : {'docs' : "Type of digest/checksum to use. Defaults to no digest", 'options': 'sha|md5'},
                         'expires' : {'docs' : "Time after ingestion at which to delete the data object in number of seconds.", 'type' : int },
                         'storeDeletions' : {'docs' : "Maintain when an object was deleted from this store.", 'type' : int, 'options' : "0|1"}
                         }

    _possibleDefaults = {'expires': {"docs" : 'Default time after ingestion at which to delete the data object in number of seconds.  Can be overridden by the individual object.', 'type' : int}}
    
    def __init__(self, session, config, parent):

        # don't inherit metadataPath!
        C3Object.__init__(self, session, config, parent)
        SummaryObject.__init__(self, session, config, parent)
        self.idNormalizer = self.get_path(session, 'idNormalizer', None)
        self.outIdNormalizer = self.get_path(session, 'outIdNormalizer', None)
        self.inWorkflow = self.get_path(session, 'inWorkflow', None)
        self.outWorkflow = self.get_path(session, 'outWorkflow', None)

        dbts = self.get_storageTypes(session)
        self.storageTypes = dbts
        revdbts = self.get_reverseMetadataTypes(session)
        self.reverseMetadataTypes = revdbts

        self.useUUID = self.get_setting(session, 'useUUID', 0)
        self.expires = self.get_default(session, 'expires', 0)

        for dbt in dbts:
            self._initDb(session, dbt)
            self._verifyDatabase(session, dbt)
            if dbt in revdbts:
                dbt = dbt + "Reverse"
                self._initDb(session, dbt)
                self._verifyDatabase(session, dbt)


    def _verifyDatabase(self, session, dbType):
        pass

    def generate_uuid(self, session):
        if (use4Suite):
            key = UuidAsString(GenerateUuid())
        else:
            key = commands.getoutput('uuidgen')
            if (len(key) != 36 or key[8] != '-'):
                # failed, generate random string instead
                lac = len(asciiChars)                
                c = [asciiChars[randomGen.randrange(lac)] for x in xrange(16)]
                key = ''.join(c)
        return key

    def generate_checkSum(self, session, data):
        digest = self.get_setting(session, "digest")
        if (digest):
            if (digest == 'md5'):
                dmod = md5
            elif (digest == 'sha'):
                dmod = sha
            else:
                raise ConfigFileException("Unknown digest type: %s" % digest)
            m = dmod.new()

            if type(data) == unicode:
                data = data.encode('utf-8')
            m.update(data)               
            digest = m.hexdigest()
            return digest
        else:
            return None

    def generate_expires(self, session, obj=None):
        now = time.time()
        if obj and hasattr(obj, 'expires'):            
            return now + obj.expires
        elif self.expires > 0:
            return now + self.expires
        else:
            # Don't expire
            return 0

    def _openAll(self, session):
        for t in self.storageTypes:
            self._open(session, t)

    def _closeAll(self, session):
        for t in self.storageTypes:
            self._close(session, t)
        for t in self.reverseMetadataTypes:
            self._close(session, t + "Reverse")

    def generate_id(self, session):
        # generate a new unique identifier
        return self.get_dbSize(session)

    def get_storageTypes(self, session):
        return ['database']

    def get_reverseMetadataTypes(self, session):
        return ['digest', 'expires']
        
    def get_dbSize(self, session):
        raise NotImplementedError

    def begin_storing(self, session):
        self._openAll(session)
        return None

    def commit_storing(self, session):
        self._closeAll(session)
        self.commit_metadata(session)
        return None

    def delete_data(self, session, id):
        # delete data stored against id
        raise NotImplementedError

    def fetch_data(self, session, id):
        # return data stored against id
        raise NotImplementedError

    def store_data(self, session, id, data, metadata):
        raise NotImplementedError

    def fetch_metadata(self, session, id, mType):
        # return mType metadata stored against id
        raise NotImplementedError

    def store_metadata(self, session, id, mType, value):
        # store value for mType metadata against id
        raise NotImplementedError
    
    def clean(self, session, force=False):
        # this would delete all the data out of self
        raise NotImplementedError

    def flush(self, session):
        # ensure all data is flushed to disk
        raise NotImplementedError

        
        





        



class BdbIter(object):
    store = None
    cursor = None
    cxn = None
    nextData = None

    def __init__(self, store):
        self.store = store
        self.session = Session()
        self.cxn = store._open(self.session, 'database')
        self.cursor = self.cxn.cursor()
        self.nextData = self.cursor.first()

    def __iter__(self):
        return self

    def next(self):
        try:
            d = self.nextData
            if not d:
                raise StopIteration()
            self.nextData = self.cursor.next()
            return d
        except:
            raise StopIteration()

    def jump(self, position):
        # Jump to this position
        self.nextData = self.cursor.set_range(position)
        return self.nextData[0]


class BdbStore(SimpleStore):
    """ Berkeley DB based storage """
    cxns = {}

    def __init__(self, session, config, parent):
        self.cxns = {}
        SimpleStore.__init__(self, session, config, parent)

    def __iter__(self):
        # Return an iterator object to iter through... keys?
        return BdbIter(self)

    def _verifyDatabase(self, session, dbType):
        dbp = self.get_path(session, dbType + "Path")
        if (not os.path.exists(dbp)):
            # We don't exist, try and instantiate new database
            self._initialise(dbp)
        else:
            cxn = bdb.db.DB()
            try:
                cxn.open(dbp)
                cxn.close()
            except:
                # Busted. Try to initialise
                self._initialise(dbp)

    def _initialise(self, dbPath):
        cxn = bdb.db.DB()
        cxn.set_flags(bdb.db.DB_RECNUM)
        try:
            cxn.open(dbPath, dbtype=bdb.db.DB_BTREE, flags = bdb.db.DB_CREATE, mode=0660)
        except:
            raise ValueError("Could not create: %s" % dbPath)
        cxn.close()

    def _open(self, session, dbType):
        cxn = self.cxns.get(dbType, None)
        if cxn == None:
            if dbType in self.storageTypes or (dbType[-7:] == 'Reverse' and dbType[:-7] in self.reverseMetadataTypes):
                cxn = bdb.db.DB()
                cxn.set_flags(bdb.db.DB_RECNUM)
                dbp = self.get_path(session, dbType + 'Path')
                if dbp:
                    if session.environment == "apache":
                        cxn.open(dbp, flags=bdb.db.DB_NOMMAP)
                    else:
                        cxn.open(dbp)
                    self.cxns[dbType] = cxn
                    return cxn
                else:
                    return None
            else:
                # trying to store something we don't care about
                return None
        else:
            return cxn

    def _close(self, session, dbType):
        cxn = self.cxns.get(dbType, None)
        if cxn != None:
            try:
                self.cxns[dbType].close()
            except:
                # silently fail, as we're closing anyway
                pass
            self.cxns[dbType] = None

    def get_dbSize(self, session):
        cxn = self._open(session, 'digest')
        if not cxn:
            cxn = self._open(session, 'database')
        return cxn.stat(bdb.db.DB_FAST_STAT)['nkeys']

    def generate_id(self, session):
        if self.useUUID:
            return self.generate_uuid(session)

        cxn = self._open(session, 'digest')
        if cxn == None:
            cxn = self._open(session, 'database')
        if (self.currentId == -1 or session.environment == "apache"):
            c = cxn.cursor()
            item = c.last()
            if item:
                # might need to out normalise key
                key = item[0]
                if self.outIdNormalizer:
                    key = self.outIdNormalizer.process_string(session, key)
                    if not type(key) in (int, long):
                        self.useUUID = 1
                        key = self.generate_uuid(session)
                    else:
                        key += 1
                else:
                    key = long(key)
                    key += 1
            else:
                key = 0
        else:
            key = self.currentId +1
        self.currentId = key
        return key

    def store_data(self, session, id, data, metadata={}):        
        dig = metadata.get('digest', "")
        if dig:
            cxn = self._open(session, 'digestReverse')
            if cxn:
                exists = cxn.get(dig)
                if exists:
                    raise ObjectAlreadyExistsException(exists)

        cxn = self._open(session, 'database')
        if (self.idNormalizer != None):
            id = self.idNormalizer.process_string(session, id)
        elif type(id) == unicode:
            id = id.encode('utf-8')
        else:
            id = str(id)

        if self.inWorkflow:
            data = self.inWorkflow.process(session, data)
        if type(data) == unicode:
            data = data.encode('utf-8')
        cxn.put(id, data)
        
        for (m, val) in metadata.iteritems():
            self.store_metadata(session, id, m, val)
        return None

    def fetch_data(self, session, id):
        cxn = self._open(session, 'database')
        if (self.idNormalizer != None):
            id = self.idNormalizer.process_string(session, id)
        elif type(id) == unicode:
            id = id.encode('utf-8')
        else:
            id = str(id)
        data = cxn.get(id)

        if data and data[:41] == "\0http://www.cheshire3.org/status/DELETED:":
            data = DeletedObject(self, id, data[41:])
        elif self.outWorkflow:
            data = self.outWorkflow.process(session, data)
        if data and self.expires:
            # update touched
            expires = self.generate_expires(session)
            self.store_metadata(session, id, 'expires', expires)
        return data
        
    def delete_data(self, session, id):
        self._openAll(session)
        cxn = self._open(session, 'database')

        if (self.idNormalizer != None):
            id = self.idNormalizer.process_string(session, id)
        elif type(id) == unicode:
            id = id.encode('utf-8')
        else:
            id = str(id)

        # main database is a storageType now
        for dbt in self.storageTypes:
            cxn = self._open(session, dbt)
            if cxn != None:
                if dbt in self.reverseMetadataTypes:
                    # fetch value here, delete reverse
                    data = cxn.get(id)
                    cxn2 = self._open(session, dbt + "Reverse")                
                    if cxn2 != None:
                        cxn2.delete(data)
                cxn.delete(id)
                cxn.sync()

        # Maybe store the fact that this object used to exist.
        if self.get_setting(session, 'storeDeletions', 0):
            cxn = self._open(session, 'database')
            now = datetime.datetime.now(dateutil.tz.tzutc()).strftime("%Y-%m-%dT%H:%M:%S%Z").replace('UTC', 'Z')            
            cxn.put(id, "\0http://www.cheshire3.org/status/DELETED:%s" % now)
            cxn.sync()


    def fetch_metadata(self, session, id, mType):
        if mType[-7:] != "Reverse":
            if (self.idNormalizer != None):
                id = self.idNormalizer.process_string(session, id)
            elif type(id) == unicode:
                id = id.encode('utf-8')
            elif type(id) != str:
                id = str(id)
        cxn = self._open(session, mType)
        if cxn != None:
            data = cxn.get(id)
            if data:
                if mType[-5:] == "Count" or mType[-8:] == "Position" or mType[-6:] in ("Amount", 'Offset'):
                    data = long(data)
                elif mType[-4:] == "Date":
                    data = dateparser.parse(data)
            return data       
        else:
            return None

    def store_metadata(self, session, id, mType, value):
        cxn = self._open(session, mType)
        if cxn != None:
            if type(value) in (int, long, float):
                value = str(value)
            cxn.put(id, value)
            if mType in self.reverseMetadataTypes:
                cxn = self._open(session, mType + "Reverse")
                if cxn != None:
                    cxn.put(value, id)
        
    def flush(self, session):
        # Call sync to flush all to disk
        for cxn in self.cxns.values():
            if cxn != None:
                cxn.sync()

    def clean(self, session, force=False):
        # check for expires unless force is true
        # NB this zeros the data pages, but does not zero the file size
        # delete the files to do that ;)

        self._openAll(session)
        if force or not self.cxns.has_key('expiresReverse'):
            deleted = self.cxns['database'].stat(bdb.db.DB_FAST_STAT)['nkeys']
            for c in self.cxns:
                self.cxns[c].truncate()
        else:
            now = time.time()
            cxn = self._open(session, 'expiresReverse')
            c = cxn.cursor()
            deleted = 0
            try:
                (key, data) = c.set_range(str(now))
                # float(time) --> object id
                if (float(key) <= now):
                    self.delete_data(session, data)
                    deleted = 1
                (key, data) = c.prev()
            except:
                # No database
                deleted = 0
                key = False
            while key:
                self.delete_data(session, data)
                deleted += 1
                try:
                    (key, data) = c.prev()
                    if not float(key):
                        break
                except:
                    # Reached beginning
                    break
        self._closeAll(session)        
        return deleted




class FileSystemIter(object):
    store = None
    cursor = None
    cxn = None
    nextData = None

    def __init__(self, store):
        self.store = store
        self.session = Session()
        self.cxn = store._open(self.session, 'byteCount')
        self.cursor = self.cxn.cursor()
        (key, val) = self.cursor.first()
        self.nextData = (key, self.store.fetch_data(self.session, key))

    def __iter__(self):
        return self

    def next(self):
        try:
            d = self.nextData
            if not d:
                raise StopIteration()
            (key, val) = self.cursor.next()
            self.nextData = (key, self.store.fetch_data(self.session, key))
            return d
        except:
            raise StopIteration()

    def jump(self, position):
        # Jump to this position
        self.nextData = self.cursor.set_range(position)
        return self.nextData[0]


class FileSystemStore(BdbStore):
    # Leave the data somewhere on disk    
    # Use metadata to map identifier to file, offset, length
    # Object to be stored needs this information, obviously!

    currFileHandle = None
    currFileName = ""


    def __iter__(self):
        return FileSystemIter(self)

    def get_storageTypes(self, session):
        return ['filename', 'byteCount', 'byteOffset']

    def get_reverseMetadataTypes(self, session):
        return ['digest', 'expires']


    def store_data(self, session, id, data, metadata={}):        
        dig = metadata.get('digest', "")
        if dig:
            cxn = self._open(session, 'digestReverse')
            if cxn:
                exists = cxn.get(dig)
                if exists:
                    raise ObjectAlreadyExistsException(exists)

        if (self.idNormalizer != None):
            id = self.idNormalizer.process_string(session, id)
        elif type(id) == unicode:
            id = id.encode('utf-8')
        else:
            id = str(id)

        if not (metadata.has_key('filename') and metadata.has_key('byteCount') and metadata.has_key('byteOffset')):
            raise SomeException("Need file, byteOffset and byteCount to use FileSystemStore")

        for (m, val) in metadata.iteritems():
            self.store_metadata(session, id, m, val)
        return None

    def fetch_data(self, session, id):
        if (self.idNormalizer != None):
            id = self.idNormalizer.process_string(session, id)
        elif type(id) == unicode:
            id = id.encode('utf-8')
        else:
            id = str(id)

        filename = self.fetch_metadata(session, id, 'filename')
        start = self.fetch_metadata(session, id, 'byteOffset')
        length = self.fetch_metadata(session, id, 'byteCount')

        if filename != self.currFileName:
            if self.currFileHandle:
                self.currFileHandle.close()
            self.currFileHandle = file(filename)
        try:
            self.currFileHandle.seek(start)
        except:
            # closed, reopen
            self.currFileHandle = file(filename)
            self.currFileHandle.seek(start)
        data = self.currFileHandle.read(length)

        if data and data[:41] == "\0http://www.cheshire3.org/status/DELETED:":
            data = DeletedObject(self, id, data[41:])
        elif self.outWorkflow:
            data = self.outWorkflow.process(session, data)

        if data and self.expires:
            # update touched
            expires = self.generate_expires(session)
            self.store_metadata(session, id, 'expires', expires)
        return data
        
    def delete_data(self, session, id):
        self._openAll(session)

        if (self.idNormalizer != None):
            id = self.idNormalizer.process_string(session, id)
        elif type(id) == unicode:
            id = id.encode('utf-8')
        else:
            id = str(id)

        filename = self.fetch_metadata(session, id, 'filename')
        start = self.fetch_metadata(session, id, 'byteOffset')
        length = self.fetch_metadata(session, id, 'byteCount')

        # main database is a storageType now
        for dbt in self.storageTypes:
            cxn = self._open(session, dbt)
            if cxn != None:
                if dbt in self.reverseMetadataTypes:
                    # fetch value here, delete reverse
                    data = cxn.get(id)
                    cxn2 = self._open(session, dbt + "Reverse")                
                    if cxn2 != None:
                        cxn2.delete(data)
                cxn.delete(id)
                cxn.sync()

        # Maybe store the fact that this object used to exist.
        if self.get_setting(session, 'storeDeletions', 0):
            now = datetime.datetime.now(dateutil.tz.tzutc()).strftime("%Y-%m-%dT%H:%M:%S%Z").replace('UTC', 'Z')            
            out = "\0http://www.cheshire3.org/status/DELETED:%s" % now

            if len(out) < length:
                f = file(filename, 'w')
                f.seek(start)
                f.write(out)
                f.close()
            else:
                # Can't write deleted status as original doc is shorter than deletion info!
                pass