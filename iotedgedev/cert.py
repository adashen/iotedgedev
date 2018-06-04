from edgectl.config import EdgeCertConfig
from edgectl.utils.certutil import EdgeCertUtil

class Cert(object):
    def __init__(self, output, certs_dir, hostname):
        self.output = output
        self.certs_dir = certs_dir
        self.hostname = hostname

    def generate(self):
        cert_config = EdgeCertConfig()
        cert_config.set_options(True, {})
        Cert._generate_self_signed_certs(cert_config, self.hostname, self.certs_dir)
    
    @staticmethod
    def _generate_self_signed_certs(certificate_config, hostname, certs_dir):
        #log.info('Generating self signed certificates at: %s', certs_dir)

        device_ca_phrase = None
        agent_ca_phrase = None
        if certificate_config.force_no_passwords is False:
            device_ca_phrase = certificate_config.device_ca_passphrase
            if device_ca_phrase is None or device_ca_phrase == '':
                bypass_opts = ['--device-ca-passphrase', '--device-ca-passphrase-file']
                device_ca_phrase = EdgeHostPlatform._prompt_password('Edge Device',
                                                                    bypass_opts,
                                                                    'deviceCAPassphraseFilePath')

            agent_ca_phrase = certificate_config.agent_ca_passphrase
            if agent_ca_phrase is None or agent_ca_phrase == '':
                bypass_opts = ['--agent-ca-passphrase', '--agent-ca-passphrase-file']
                agent_ca_phrase = EdgeHostPlatform._prompt_password('Edge Agent',
                                                                    bypass_opts,
                                                                    'agentCAPassphraseFilePath')

        cert_util = EdgeCertUtil()
        cert_util.create_root_ca_cert('edge-device-ca',
                                    validity_days_from_now=365,
                                    subject_dict=certificate_config.certificate_subject_dict,
                                    passphrase=device_ca_phrase)
        Cert._generate_certs_common(cert_util,
                                    hostname,
                                    certs_dir,
                                    agent_ca_phrase)


    @staticmethod
    def _generate_certs_common(cert_util, hostname, certs_dir, agent_ca_phrase):
        cert_util.export_cert_artifacts_to_dir('edge-device-ca', certs_dir)

        cert_util.create_intermediate_ca_cert('edge-agent-ca',
                                            'edge-device-ca',
                                            validity_days_from_now=365,
                                            common_name='Edge Agent CA',
                                            set_terminal_ca=True,
                                            passphrase=agent_ca_phrase)

        cert_util.export_cert_artifacts_to_dir('edge-agent-ca', certs_dir)

        cert_util.create_server_cert('edge-hub-server',
                                    'edge-agent-ca',
                                    validity_days_from_now=365,
                                    hostname=hostname)


        cert_util.export_cert_artifacts_to_dir('edge-hub-server', certs_dir)
        cert_util.export_pfx_cert('edge-hub-server', certs_dir)

        prefixes = ['edge-agent-ca', 'edge-device-ca']
        cert_util.chain_ca_certs('edge-chain-ca', prefixes, certs_dir)
