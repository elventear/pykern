# -*-groovy-*-
# vi: set ft=groovy :

node {
    stage 'checkout'
    checkout scm

    stage 'install preqreqs'
    sh 'pip install -U pip setuptools tox'
    sh 'pip install -r requirements.txt'

    stage 'run test'
    sh 'python setup.py pkdeploy'
}
