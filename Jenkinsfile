#!/usr/bin/env groovy

// -*-groovy-*-
// vi: set ft=groovy :

dockerNode(image: "radiasoft/python2") {
    stage 'checkout'
    checkout scm

    stage 'install preqreqs'
    sh 'pip install -U pip setuptools tox'
    sh 'pip install -r requirements.txt'

    stage 'run test'
    sh 'python setup.py pkdeploy'
}
