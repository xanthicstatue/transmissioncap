transmissioncap
===============

You will need to define a s_info.py file

Python 2.7.x script to add a data transfer cap to transmission.  Requires transmissionrpc0.9 or newer.

Meant to be added to crontab. Sample entry below

"*/5 * * * * ~/Documents/transmission/transmissioncap.py >> ~/cronlog.txt 2>&1"
