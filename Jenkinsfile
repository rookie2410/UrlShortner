pipeline {
    agent any

    environment {
        DOCKERHUB_USER = 'rookie241099'
        BACKEND_IMAGE  = 'rookie241099/shortlink-backend'
        FRONTEND_IMAGE = 'rookie241099/shortlink-frontend'
	APP_HOST = '172.31.29.77'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Build Docker Images') {
            steps {
                script {
                    env.IMAGE_TAG = sh(
                        script: 'git rev-parse --short=7 HEAD',
                        returnStdout: true
                    ).trim()
                }

                sh '''
                    docker build -t ${BACKEND_IMAGE}:${IMAGE_TAG} \
                                 -t ${BACKEND_IMAGE}:latest \
                                 -f backend/Dockerfile backend

                    docker build -t ${FRONTEND_IMAGE}:${IMAGE_TAG} \
                                 -t ${FRONTEND_IMAGE}:latest \
                                 -f frontend/Dockerfile frontend
                '''
            }
        }

        stage('Push to Docker Hub') {
            steps {
                withCredentials([
                    usernamePassword(
                        credentialsId: 'dockerhub-creds',
                        usernameVariable: 'DOCKER_USER',
                        passwordVariable: 'DOCKER_TOKEN'
                    )
                ]) {
                    sh '''
                        set +x
                        echo "$DOCKER_TOKEN" | docker login \
                            -u "$DOCKER_USER" --password-stdin

                        docker push ${BACKEND_IMAGE}:${IMAGE_TAG}
                        docker push ${BACKEND_IMAGE}:latest

                        docker push ${FRONTEND_IMAGE}:${IMAGE_TAG}
                        docker push ${FRONTEND_IMAGE}:latest

                        docker logout
                    '''
                }
            }
        }
    }

    post {
        always {
            sh 'docker logout >/dev/null 2>&1 || true'
        }
    }
}
