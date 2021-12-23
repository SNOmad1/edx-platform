"""
Utilities for logging sensitive debug information such as authentication tokens.

Usage:

1. Read the warning in cli_gen_keys
2. Generate keys using ``python3 -m common.djangoapps.util.log_sensitive gen-keys``
   and follow the instructions it prints out
3. When logging sensitive information, use like so::

     logger.info(
         "Received invalid auth token %s in Authorization header",
         encrypt_for_log(token, settings.AUTH_ERRORS_DEBUG_KEYS)
     )

   This will log a message like::

     Received invalid auth token ZXIzljFT7zTTuXyIB/jy4XTixL34EhI6pY0Gw4mxfFo=|IYS4JDE0S9wypALb5HfoeW9YB/CnSx35/PkspsecZyzTP1Zr8B/W+16Gfe+pRZhjBitQ66XTZk9YHwKfznQ1KA== in Authorization header

4. If you need to decrypt one of these messages, save the encrypted portion
   to file, retrieve the securely held private key, and run::

     python3 -m common.djangoapps.util.log_sensitive decrypt --message-file ... --private-key-file ...

   If possible, use bash process indirection to keep the private key from
   touching disk unencrypted, e.g. ``--private-key-file <(gpg2 --decrypt auth-logging-key.enc)``
"""

from base64 import b64decode, b64encode

import click
from nacl.public import Box, PrivateKey, PublicKey

# Background:
#
# The NaCl "Box" construction provides asymmetric encryption, allowing
# the sender to encrypt something for a recipient without having a
# shared secret. This encryption is authenticated, meaning that the
# recipient verifies that the message matches the sender's public key
# (proof of sender). But it's also *repudiable* authentication; the
# design allows both the sender and the receiver to read (or have
# created!) the encrypted message, so the receipient can't prove to
# anyone *else* that the sender was the author.
#
# Why we use ephemeral sender keys:
#
# The Box is normally an ideal construction to use for
# communications. However, we don't want the logger to be able to read
# the messages it writes, especially not messages from a different
# server instance or from days or weeks ago. Only developers (or
# others) in possession of the recipient keypair should be able to
# read it, not anyone who compromises a server at some later
# date. Luckily, we also don't care about authenticating the logged
# messages as truly being from the server! The solution is for each
# server to create a fresh public/private keypair at startup and to
# include a copy of the public key in any encrypted logs it writes.


# Generate an ephemeral private key for the logger to use during this
# logging session.
logger_private_key = PrivateKey.generate()


def encrypt_for_log(message, reader_public_key_b64):
    """
    Encrypt a message so that it can be logged but only read by someone
    possessing the given public key. The public key is provided in base64.

    A separate public key should be used for each recipient or purpose.

    Returns a string <sender public key> "|" <ciphertext> which can be
    decrypted with decrypt_log_message.
    """
    reader_public_key = PublicKey(b64decode(reader_public_key_b64))

    encrypted = Box(logger_private_key, reader_public_key).encrypt(message.encode())

    pubkey = logger_private_key.public_key
    return b64encode(bytes(pubkey)).decode() + '|' + b64encode(encrypted).decode()


def decrypt_log_message(encrypted_message, reader_private_key_b64):
    """
    Decrypt a message using the private key that has been stored somewhere
    secure and *not* on the server.
    """
    reader_private_key = PrivateKey(b64decode(reader_private_key_b64))
    sender_public_key_data, encrypted_raw = \
        [b64decode(part) for part in encrypted_message.split('|', 1)]
    return Box(reader_private_key, PublicKey(sender_public_key_data)).decrypt(encrypted_raw).decode()


def generate_reader_keys():
    """
    Utility method for generating a public/private keypair for use with these
    logging functions. Returns a pair of base64
    """
    reader_private_key = PrivateKey.generate()
    return {
        'public': b64encode(bytes(reader_private_key.public_key)).decode(),
        'private': b64encode(bytes(reader_private_key)).decode(),
    }


@click.group()
def cli():
    pass


@click.command('gen-keys', help="Generate keypair")
def cli_gen_keys():
    """
    Generate and print a keypair for handling sensitive log messages.
    """
    reader_keys = generate_reader_keys()
    public_64 = reader_keys['public']
    private_64 = reader_keys['private']
    print(
        "This is your PUBLIC key, which should be included in the server's "
        "configuration. Create a separate setting (and keypair) for each "
        "distinct project or team. This value does not need special protection:"
        "\n\n"
        f"  \"{public_64}\" (public)"
        "\n\n"
        "This is your PRIVATE key, which must never be present on the server "
        "and should instead be kept encrypted in a separate, safe place "
        "such as a password manager:"
        "\n\n"
        f"  \"{private_64}\" (private)"
        "\n\n"
        "Before logging anything sensitive, get a legal/compliance review to "
        "ensure this is acceptable in your organization. Encryption is not "
        "generally a replacement for retention policies or other privacy "
        "safeguards; using this utility does not automatically make sensitive "
        "information safe to handle."
    )


@click.command('decrypt', help="Decrypt a logged message")
@click.option(
    '--private-key-file', type=click.File('r'), required=True,
    help="Path to file containing reader's private key in Base64",
)
@click.option(
    '--message-file', type=click.File('r'), required=True,
    help="Path to file containing encrypted message, or - for stdin",
)
def cli_decrypt(private_key_file, message_file):
    """
    Decrypt a message and print it to stdout.
    """
    print(decrypt_log_message(message_file.read(), private_key_file.read()))


@click.command('encrypt', help="Encrypt a one-off message")
@click.option('--public-key', help="Reader's public key, in Base64")
@click.option(
    '--message-file', type=click.File('r'), required=True,
    help="Path to file containing message to encrypt, or - for stdin",
)
def cli_encrypt(public_key, message_file):
    """
    Encrypt a message to the provided public key and print it to stdout.

    This is just intended for use when testing or experimenting with the decrypt command.
    """
    print(encrypt_for_log(message_file.read(), public_key))


cli.add_command(cli_gen_keys)
cli.add_command(cli_decrypt)
cli.add_command(cli_encrypt)

if __name__ == '__main__':
    cli()
