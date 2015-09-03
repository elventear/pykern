#!/bin/bash
echo "$(date): $TRAVIS_JOB_NUMBER"
date > somejunk-$TRAVIS_JOB_NUMBER.pyc
if [[ $TRAVIS_JOB_NUMBER =~ \.1$ ]]; then
    exit 0
fi
echo "$(date): Sleeping for 60 seconds"
sleep 60
echo "$(date): done sleeping"
echo "$(date): ERROR do not deploy!"
exit 1