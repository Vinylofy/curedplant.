"""FTPS failures expose actionable stages without account/server messages."""
from datetime import datetime, timezone
import ftplib
import os
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.importers.bol_feed import download_feed, FeedError


class BolFtpsTests(unittest.TestCase):
    def test_failure_stages_keep_credentials_and_raw_messages_private(self):
        cases = [
            ('connect', TimeoutError('private-account'), 'connect', 'timeout'),
            ('auth', ssl.SSLCertVerificationError('private-account'), 'tls_auth', 'certificate_verification'),
            ('login', ftplib.error_perm('530 private-account private-password'), 'login', 'ftp_rejected ftp_status=530'),
            ('sendcmd', ftplib.error_perm('550 private-account file missing'), 'feed_timestamp', 'ftp_rejected ftp_status=550'),
            ('retrbinary', ssl.SSLError('private-account data channel'), 'download', 'tls_error'),
        ]
        for method, failure, stage, reason in cases:
            with self.subTest(method=method), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'feed.gz'
                path.write_bytes(b'partial')
                ftp = Mock()
                ftp.sendcmd.return_value = '213 20261021120000'
                getattr(ftp, method).side_effect = failure
                context = Mock()
                context.__enter__ = Mock(return_value=ftp)
                context.__exit__ = Mock(return_value=False)
                with patch.dict(os.environ, {'BOL_FEED_USERNAME': 'private-account', 'BOL_FEED_PASSWORD': 'private-password'}), \
                     patch('scripts.importers.bol_feed.ftplib.FTP_TLS', return_value=context), \
                     self.assertRaises(FeedError) as caught:
                    download_feed(path)
                self.assertEqual(str(caught.exception), f'feed_download_failed stage={stage} reason={reason}')
                self.assertFalse(path.exists())
                self.assertNotIn('private-account', str(caught.exception))
                self.assertNotIn('private-password', str(caught.exception))

    def test_verified_tls_protected_data_and_download_timestamp_are_preserved(self):
        ftp = Mock()
        ftp.sendcmd.return_value = '213 20261021120000'
        ftp.retrbinary.side_effect = lambda command, receive: receive(b'feed bytes')
        context = Mock()
        context.__enter__ = Mock(return_value=ftp)
        context.__exit__ = Mock(return_value=False)
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {'BOL_FEED_USERNAME': 'account', 'BOL_FEED_PASSWORD': 'password'}), \
             patch('scripts.importers.bol_feed.ftplib.FTP_TLS', return_value=context) as client:
            path = Path(directory) / 'feed.gz'
            timestamp = download_feed(path)
            self.assertEqual(path.read_bytes(), b'feed bytes')
            self.assertEqual(timestamp, datetime(2026, 10, 21, 12, tzinfo=timezone.utc))
            tls = client.call_args.kwargs['context']
            self.assertEqual(tls.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(tls.check_hostname)
            self.assertEqual([call[0] for call in ftp.method_calls][:5],
                             ['connect', 'auth', 'login', 'prot_p', 'set_pasv'])
            ftp.set_pasv.assert_called_once_with(True)

    def test_recent_successful_checkpoint_skips_retrieval(self):
        ftp = Mock()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        ftp.sendcmd.return_value = '213 ' + now.strftime('%Y%m%d%H%M%S')
        context = Mock()
        context.__enter__ = Mock(return_value=ftp)
        context.__exit__ = Mock(return_value=False)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                'BOL_FEED_USERNAME': 'account', 'BOL_FEED_PASSWORD': 'password'}), patch(
                'scripts.importers.bol_feed.ftplib.FTP_TLS', return_value=context):
            path = Path(directory) / 'feed.gz'
            self.assertEqual(download_feed(path, unchanged_since=now), now)
            self.assertFalse(path.exists())
            ftp.retrbinary.assert_not_called()

    def test_source_changed_during_transfer_cannot_be_published(self):
        ftp = Mock()
        ftp.sendcmd.side_effect = ['213 20261107100000', '213 20261107120000']
        ftp.retrbinary.side_effect = lambda command, receive: receive(b'feed bytes')
        context = Mock()
        context.__enter__ = Mock(return_value=ftp)
        context.__exit__ = Mock(return_value=False)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                'BOL_FEED_USERNAME': 'account', 'BOL_FEED_PASSWORD': 'password'}), patch(
                'scripts.importers.bol_feed.ftplib.FTP_TLS', return_value=context):
            path = Path(directory) / 'feed.gz'
            with self.assertRaisesRegex(FeedError, 'feed_changed_during_download'):
                download_feed(path, attempts=1)
            self.assertFalse(path.exists())

    def test_writer_timeout_reports_safe_stage_without_driver_text(self):
        import psycopg
        from scripts.importers.bol_feed import SafeWriterCursor
        cursor = Mock()
        cursor.execute.side_effect = psycopg.errors.QueryCanceled('private-account private-password')
        wrapped = SafeWriterCursor(cursor)
        for query, stage in [("select pg_advisory_xact_lock(hashtextextended('bol-affiliate-import',0))", "source_lock"),
                             ("select 1 from public.raw_shop_scrapes where shop_id=%s", "raw_shop_scrapes_read")]:
            with self.assertRaises(FeedError) as failure:
                wrapped.execute(query)
            self.assertEqual(str(failure.exception), 'database_statement_timeout stage=' + stage)

    def test_oversize_transfer_still_aborts_and_removes_partial_file(self):
        ftp = Mock()
        ftp.sendcmd.return_value = '213 20261021120000'
        ftp.retrbinary.side_effect = lambda command, receive: receive(b'too large')
        context = Mock()
        context.__enter__ = Mock(return_value=ftp)
        context.__exit__ = Mock(return_value=False)
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {'BOL_FEED_USERNAME': 'account', 'BOL_FEED_PASSWORD': 'password'}), \
             patch('scripts.importers.bol_feed.ftplib.FTP_TLS', return_value=context):
            path = Path(directory) / 'feed.gz'
            with self.assertRaisesRegex(FeedError, '^feed_download_size_limit$'):
                download_feed(path, max_bytes=1)
            self.assertFalse(path.exists())
