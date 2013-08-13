#!/usr/bin/env python
'''
* Copyright (c) 2013 Jeremy Parks. All rights reserved.
*
* Permission is hereby granted, free of charge, to any person obtaining a
* copy of this software and associated documentation files (the "Software"),
* to deal in the Software without restriction, including without limitation
* the rights to use, copy, modify, merge, publish, distribute, sublicense,
* and/or sell copies of the Software, and to permit persons to whom the
* Software is furnished to do so, subject to the following conditions:
*
* The above copyright notice and this permission notice shall be included in
* all copies or substantial portions of the Software.
*
* THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
* IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
* FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
* AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
* LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
* FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
* DEALINGS IN THE SOFTWARE.

Author: Jeremy Parks
Purpose: To add a daily and monthly transfer cap to Transmission
Notes: This script will only resume all torrents if there are no active torrents when it tries to resume
search for #~ for options on changing parts of the code
'''

import transmissionrpc
import time
import os
import syslog, sys
from dbdict import PersistentDict # from http://code.activestate.com/recipes/576642-persistent-dict-with-multiple-standard-file-format/

##START GLOBALS##

#~ Change these values to match your environment
from s_info import server, s_port, s_user, s_pass

cap = 200 #~ bandwidth cap in gigaBytes
date = time.time() + 10800 #~ adjusted for EST since Comcast uses EST to reset monthly cap


# Don't change these
currentYear = str(time.localtime(date).tm_year)
currentMonth = str(time.localtime(date).tm_mon)
currentDay = str(time.localtime(date).tm_mday)
monthlyCap = cap * 1073741824 # convert to Bytes
daily_ratio = float(currentDay)

if int(currentMonth) in {1,3,5,7,8,10,12}:
	daily_ratio = float(daily_ratio)/31 
elif int(currentMonth) in {4,6,9,11}:
	daily_ratio = float(daily_ratio)/30
else: #it's february
	if int(currentYear)%400 == 0:
		daily_ratio = float(daily_ratio)/29
	elif int(currentYear)%100 == 0:
		daily_ratio = float(daily_ratio)/28
	elif int(currentYear)%4 == 0:
		daily_ratio = float(daily_ratio)/29
	else:
		daily_ratio = float(daily_ratio)/28

dailyCap = monthlyCap * daily_ratio # rolling daily cap so not bandwidth capped at beginning of month


##END GLOBALS##

# helper function to start all torrents and enable start on add.  Meant to be called directly via
# python -c 'import <filename>; <filename>.forceStart()'
def forceStart():
	# sign in to our transmission client so we can get information and issue commands
	tc = transmissionrpc.Client(server,port=s_port,user=s_user,password=s_pass)
	for i in tc.get_torrents():
		tc.start_torrent(i.id)
	tc.set_session(start_added_torrents=True)

# function to stop all torrents and disable autostart
def stopTorrents(tc,s_stats):
	tc.set_session(start_added_torrents=False)
	for i in tc.get_torrents():
		tc.stop_torrent(i.id)

# function to start all torrents and enable autostart
def startTorrents(tc,s_stats):
	tc.set_session(start_added_torrents=True)
	for i in tc.get_torrents():
		tc.start_torrent(i.id)



# attempt to open our database
# If database is not found or it is a new day a default dictionary entry will be created
def SetupDB():
	myDB = PersistentDict('./transm_log.json' , 'c', format='json')
	myDB.setdefault('lastUsage', 0)
	myDB.setdefault('data', {})
	myDB['data'].setdefault(currentYear, {})
	myDB['data'][currentYear].setdefault(currentMonth, {})
	myDB['data'][currentYear][currentMonth].setdefault(currentDay, [])
	return myDB

# determine how much bandwidth we have used since last check
# This will capture cumulative stat resets
def GetIncrementalUsage(myDB,current):
	usage = current 
	lastUsage = myDB["lastUsage"]
	if lastUsage == 0: # in most scenarios if lastUsage is 0 there was an error somewhere.
		incr = 0
	elif usage >= lastUsage:
		incr = usage - lastUsage
	else:
		incr = usage
	myDB["lastUsage"] = usage
	return incr

#~ if we didn't want each incremental usage for the day we would use += incr instead of append
def UpdateUsage(myDB,current):
	incr = GetIncrementalUsage(myDB,current)
	myDB["data"][currentYear][currentMonth][currentDay].append(incr)

#helper function to check if we are over our limits
def OverLimits(myDB):
	usageThisMonth = sum(sum(x) for x in myDB['data'][currentYear][currentMonth].values())
	if usageThisMonth > dailyCap:
		syslog.syslog(syslog.LOG_NOTICE,"Over daily cap")
		return True

	if usageThisMonth > monthlyCap:
		syslog.syslog(syslog.LOG_NOTICE,"Over monthly cap")
		return True

	syslog.syslog(syslog.LOG_INFO,"Daily cap remaining:%s Monthly cap remaining:%s " % (str(float(dailyCap-usageThisMonth)/1073741824),str(float(monthlyCap-usageThisMonth)/1073741824)))
	return False
	
if __name__ == '__main__':
	# set up logging
	lvl = syslog.LOG_DEBUG #~ valid values are LOG_EMERG, LOG_ALERT, LOG_CRIT, LOG_ERR, LOG_WARNING, LOG_NOTICE, LOG_INFO, LOG_DEBUG.
	syslog.setlogmask(syslog.LOG_UPTO(lvl)) #~ change to control what is written to log file
	# set up database
	myDB = SetupDB()


	try:
		# sign in to our transmission client so we can get information and issue commands
		tc = transmissionrpc.Client(server,port=s_port,user=s_user,password=s_pass)
		# take a snapshot 
		s_stats = tc.session_stats()
 		# we won't have 288 entries per day in the database this way
		#~ if we want all 288 entires, move UpdateUsage outside of the if statement
		if s_stats.activeTorrentCount > 0:
			#if status == downloading, reannounce
# TODO fix this
			for i in tc.get_torrents():
				if i.status == 'downloading':
					tc.reannounce_torrent(i.id)	
			
			# get transmissions current total transfer stats
			current = s_stats.cumulative_stats['downloadedBytes']+s_stats.cumulative_stats['uploadedBytes']
			if current == 0:
				syslog.syslog(syslog.LOG_WARNING, "Something went wrong, usage should not be 0")
				exit(0) # end execution
			UpdateUsage(myDB,current) 

			if OverLimits(myDB):
				stopTorrents(tc,s_stats)
				usageThisMonth = sum(sum(x) for x in myDB['data'][currentYear][currentMonth].values())

		if lvl == syslog.LOG_INFO or lvl == syslog.LOG_DEBUG: # this only runs if we are logging info messages
			usageThisMonth = sum(sum(x) for x in myDB['data'][currentYear][currentMonth].values())
			if usageThisMonth >= monthlyCap:
				syslog.syslog(syslog.LOG_INFO, "Monthly cap exceeded. %s" % str(float(monthlyCap-usageThisMonth)/1073741824))
			else:
				syslog.syslog(syslog.LOG_INFO,"Daily cap remaining %s. Monthly cap remaining:%s " % (str(float(dailyCap-usageThisMonth)/1073741824),str(float(monthlyCap-usageThisMonth)/1073741824)))
		# if this is the first run of the day, start the torrents
		if time.localtime(date).tm_hour == 0 and time.localtime(date).tm_min < 8: # and not OverLimits(myDB): #~ if you don't run this script during the first 7 minutes of the day you need to chance the range.
			startTorrents(tc,s_stats)
	except Exception, error:
		print error
		# log the error
		syslog.syslog(syslog.LOG_ERR,str(error))

	finally:
		# sync DB
		myDB.close()
