"""Deployment boundary regression for Django + Vite lazy CSS blank screens."""
from pathlib import Path
import re
from django.conf import settings
from django.test import SimpleTestCase, override_settings


@override_settings(DEBUG=False)
class FrontendReleaseTests(SimpleTestCase):
    def test_production_home_and_lazy_assets_share_django_static_prefix(self):
        assets = Path(settings.BASE_DIR) / 'static/frontend/assets'
        if not assets.is_dir():
            self.skipTest('Build the frontend before release validation')
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        html = response.content.decode()
        entry = re.search(r'src="(/static/frontend/assets/index-[^\"]+\.js)"', html)
        self.assertIsNotNone(entry)
        source = (Path(settings.BASE_DIR) / entry[1].lstrip('/')).read_text(encoding='utf-8')
        # Check the emitted preload URL transform, not just the HTML entry tag.
        self.assertRegex(source, r'return[\"\u0027]/static/frontend/[\"\u0027]\+')
        dependencies = set(re.findall(r'"(assets/[^\"]+\.(?:js|css))"', source))
        self.assertGreater(len(dependencies), 5)
        for dependency in dependencies:
            with self.subTest(asset=dependency):
                result = self.client.get('/static/frontend/' + dependency)
                self.assertEqual(result.status_code, 200)
                self.assertIn('text/css' if dependency.endswith('.css') else 'javascript', result['Content-Type'])
                result.close()
