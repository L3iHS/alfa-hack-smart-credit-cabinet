from app.processing.policy import POLICY_VERSION

CONSENT_VERSION = 'submission-consent-v2'
MAX_FILE_SIZE = 10 * 1024 * 1024
ACCEPTED_CONTENT_TYPES = ('application/pdf', 'image/png', 'image/jpeg')
DATA_CONFIRMATION_TEXT = 'Подтверждаю, что проверил данные заявки.'
BKI_CONSENT_TEXT = 'Согласен на проверку кредитной истории.'


def submission_policy():
    return {
        'consent_version': CONSENT_VERSION,
        'data_confirmation_text': DATA_CONFIRMATION_TEXT,
        'bki_consent_text': BKI_CONSENT_TEXT,
        'max_file_size_bytes': MAX_FILE_SIZE,
        'accepted_content_types': ACCEPTED_CONTENT_TYPES,
    }
