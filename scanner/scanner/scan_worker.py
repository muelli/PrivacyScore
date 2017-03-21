#-*- coding: utf-8 -*-
import string
import json
from datetime import datetime
from bson.objectid import ObjectId
from pymongo import MongoClient
import os 
import sys
from scan_connector import ScannerConnector
from db_connector import DBConnector
from externaltests_connector import ExternalTestsConnector

DBConnector = DBConnector()
ScannerConnector = ScannerConnector()
ExternalTestsConnector = ExternalTestsConnector()

# FIXME Hardcoded MongoDB-Host
client = MongoClient('mongodb://localhost:27017/')
db = client['PrangerDB']

readylists = db.ScanGroup.find({'state': 'ready'}).count()
scanninglists = db.ScanGroup.find({'state': 'scanning'}).count()

if scanninglists < 3 and readylists > 0:
    scannablelist = db.ScanGroup.aggregate([{'$match': {'state': 'ready'}},{'$sort': {'startdate': -1}}, {'$limit': 1}])
    x = list(scannablelist)
    if len(x) > 0:
        for list in x:
            urls = []
            list_id = list['list_id']
            scangroup_id = list['_id']

            # Note: This is a race condition waiting to happen if a scan has not terminated before a rescan is started.
            # But I don't have a better idea right now.
            # FIXME Hardcoded path
            fname = "/home/nico/WPM-Scans/%s/crawl-data.sqlite" %  str(list_id)
            if os.path.isfile(fname):
                os.remove(fname)

            # FIXME Hardcoded path
            f = open("/home/nico/WPM-Scans/scans.txt", 'a')
            f.write("Listen-ID: " + str(list_id))
            f.write(os.linesep)
            f.close()

            # TODO Retrieving websites from MongoDB - refactor
            urlsCursor = db.Seiten.find({'list_id': ObjectId(list_id)}, {'_id': 1, 'url': 1})
            for url in urlsCursor:
                urls.append(url)

            # TODO State-keeping in mongoDB - refactor?
            db.ScanGroup.update({'_id': ObjectId(scangroup_id)}, {'$set': {'state': 'scanning'}})
            db.ScanGroup.update({'_id': ObjectId(scangroup_id)}, {'$set': {'progress': "Initializing"}})
            db.ScanGroup.update({'_id': ObjectId(scangroup_id)}, {'$set':{'progress_timestamp': datetime.now().isoformat()}}, upsert=False)

            # Scan using OpenWTM
            # TODO Move to Celery task
            state = ScannerConnector.startscan(urls, list_id, scangroup_id)
            if state.startswith('error'):
                db.ScanGroup.update({'_id': ObjectId(scangroup_id)}, {'$set': {'state': "error in ScannerConnector.startscan - %s" % state}})
                sys.exit("error in ScannerConnector.startscan - %s" % state)

            # Run external tests
            # TODO Move to Celery task
            state = ExternalTestsConnector.RunExternalTests(list_id, scangroup_id, urls)
            if state.startswith('error'):
                db.ScanGroup.update({'_id': ObjectId(scangroup_id)}, {'$set': {'state': "error during RunExternalTests - %s" % state}})
                sys.exit("error during RunExternalTests - %s" % state)

            # Save results to MongoDB
            # TODO This will have to be moved to a different place in the long run, once we use Celery tasks
            state = DBConnector.SaveScan(list_id, scangroup_id, urls)
            # TODO The following is just error handling for the insert - will probably also have to be moved (statekeeping in MongoDB)
            if state.startswith('error'):
                db.ScanGroup.update({'_id': ObjectId(scangroup_id)}, {'$set': {'state': "error during SaveScan - %s" % state}})
                sys.exit("error during SaveScan - %s" % state)

            elif state.startswith('success'):
                db.ScanGroup.update({'_id': ObjectId(scangroup_id)}, {'$set': {'state': 'finish'}})
                db.ScanGroup.update({'_id': ObjectId(scangroup_id)}, {'$set': {'progress': "finish"}})
                db.ScanGroup.update({'_id': ObjectId(scangroup_id)}, {'$set':{'progress_timestamp': datetime.now().isoformat()}}, upsert=False)
                sys.exit()

            else:
                db.ScanGroup.update({'_id': ObjectId(scangroup_id)}, {'$set': {'state': 'unknown error during SaveScan: no status returned'}})
                sys.exit("unknown error during SaveScan: no status returned")
