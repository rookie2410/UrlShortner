
pipeline {
    agent any

    environment {
        BACKEND_IMAGE  = 'rookie241099/shortlink-backend'
        FRONTEND_IMAGE = 'rookie241099/shortlink-frontend'
        APP_HOST       = '172.31.29.77'
        APP_USER       = 'ubuntu'
        DEPLOY_DIR     = '/opt/shortlink'
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
                    docker build \
                        -t ${BACKEND_IMAGE}:${IMAGE_TAG} \
                        -t ${BACKEND_IMAGE}:latest \
                        -f backend/Dockerfile backend

                    docker build \
                        -t ${FRONTEND_IMAGE}:${IMAGE_TAG} \
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

        stage('Deploy to App EC2') {
            steps {
                sshagent(credentials: ['shortlink-ssh-key']) {
                    withCredentials([
                        file(
                            credentialsId: 'shortlink-env',
                            variable: 'ENV_FILE'
                        )
                    ]) {
                        sh '''
                            set -eu

                            echo "Creating deployment directory..."

                            ssh ${APP_USER}@${APP_HOST} \
                                "mkdir -p ${DEPLOY_DIR}"

                            echo "Transferring Compose configuration..."

                            scp docker-compose.yml \
                                ${APP_USER}@${APP_HOST}:${DEPLOY_DIR}/docker-compose.yml

                            echo "Transferring production environment..."

                            scp "$ENV_FILE" \
                                ${APP_USER}@${APP_HOST}:${DEPLOY_DIR}/.env

                            ssh ${APP_USER}@${APP_HOST} \
                                "chmod 600 ${DEPLOY_DIR}/.env"

                            echo "Pulling images: ${IMAGE_TAG}"

                            ssh ${APP_USER}@${APP_HOST} \
                                "cd ${DEPLOY_DIR} && \
                                 IMAGE_TAG=${IMAGE_TAG} docker compose pull"

                            echo "Starting application..."

                            ssh ${APP_USER}@${APP_HOST} \
                                "cd ${DEPLOY_DIR} && \
                                 IMAGE_TAG=${IMAGE_TAG} docker compose up -d \
                                 --remove-orphans --wait --wait-timeout 120"

                            echo "Deployment status..."

                            ssh ${APP_USER}@${APP_HOST} \
                                "cd ${DEPLOY_DIR} && docker compose ps"
                        '''
                    }
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

