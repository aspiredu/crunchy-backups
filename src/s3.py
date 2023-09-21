import boto3


def get_s3(access_key_id, secret_access_key, session_token=None):
    session = boto3.session.Session(
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        aws_session_token=session_token,
    )
    return session.resource("s3"), session.client("s3")
