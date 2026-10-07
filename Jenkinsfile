// Locale validation pipeline.
//
// Result policy (see NOTES.md):
//   validator exit 0 -> SUCCESS
//   validator exit 1 -> UNSTABLE  (translations have gaps: visible, but not a broken build)
//                       FAILURE   if STRICT=true (e.g. release branches / pre-merge gate)
//   anything else    -> FAILURE   (the tooling itself broke: no Python, bad en.json, bad path)

pipeline {
    agent any

    parameters {
        string(
            name: 'LOCALES_DIR',
            defaultValue: 'locales',
            trim: true,
            description: 'Locales directory to validate, relative to the repo root.'
        )
        booleanParam(
            name: 'STRICT',
            defaultValue: false,
            description: 'Fail the build (instead of UNSTABLE) when locale problems are found.'
        )
    }

    options {
        // "Pipeline script from SCM" already checks out once to read this file;
        // skip the implicit checkout so the explicit Checkout stage is the only one.
        skipDefaultCheckout(true)
        timeout(time: 10, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
        disableConcurrentBuilds()
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                sh 'git log -1 --oneline'
            }
        }

        stage('Validate') {
            steps {
                script {
                    // returnStatus: we decide the build result ourselves instead of
                    // letting any non-zero exit kill the stage (and skip Report).
                    // Single-quoted Groovy string: $LOCALES_DIR is expanded by the
                    // shell from the environment, not interpolated by Groovy, so a
                    // parameter value cannot inject shell code.
                    env.VALIDATOR_RC = sh(
                        script: 'bash tools/run_checks.sh "$LOCALES_DIR"',
                        returnStatus: true
                    ).toString()
                    echo "Validator exit code: ${env.VALIDATOR_RC}"
                }
            }
        }

        stage('Report') {
            steps {
                // allowEmptyArchive: if the wrapper died before writing the report,
                // don't let a missing artifact hide the real error.
                archiveArtifacts artifacts: 'reports/locale-report.txt',
                                 allowEmptyArchive: true,
                                 fingerprint: true
            }
        }

        stage('Quality Gate') {
            steps {
                script {
                    def rc = env.VALIDATOR_RC.toInteger()
                    if (rc == 0) {
                        echo 'All locales match en.json.'
                    } else if (rc == 1 && !params.STRICT) {
                        unstable('Locale problems found - see locale-report.txt')
                    } else if (rc == 1) {
                        error('Locale problems found and STRICT=true')
                    } else {
                        error("Validation tooling failed (exit ${rc}) - this is not a translation problem")
                    }
                }
            }
        }
    }

    post {
        success {
            echo "PASSED: locales in '${params.LOCALES_DIR}' are clean."
        }
        unstable {
            echo "UNSTABLE: translation gaps in '${params.LOCALES_DIR}'. Report: ${env.BUILD_URL}artifact/reports/locale-report.txt"
        }
        failure {
            echo "FAILED: check the console log above. Validator exit code: ${env.VALIDATOR_RC ?: 'n/a (failed before validation)'}"
            // Real pipeline: notify the L10n channel / owners here (Slack, email, Jira).
        }
        cleanup {
            deleteDir()
        }
    }
}
