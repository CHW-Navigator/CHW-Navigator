'use strict';

const path = require('node:path');

const [harnessModule, appSettingsPath, xformFolder, form, executablePath] = process.argv.slice(2);
if (executablePath) {
  const resolverPath = require.resolve('puppeteer-chromium-resolver', {
    paths: [path.resolve(harnessModule)],
  });
  const resolver = require(resolverPath);
  const stats = resolver.getStats();
  require.cache[resolverPath].exports = async () => ({ ...stats, executablePath });
}
const Harness = require(path.resolve(harnessModule));

async function main() {
  const harness = new Harness({
    appXFormFolderPath: path.resolve(xformFolder),
    appSettingsPath: path.resolve(appSettingsPath),
    coreVersion: '4.11',
    subject: 'patient-1',
    content: { source: 'contact' },
    docs: [
      { _id: 'default_user', type: 'person', name: 'CHW' },
      {
        _id: 'patient-1',
        type: 'person',
        name: 'Registered child',
        date_of_birth: '2024-03-05',
      },
    ],
    ...(executablePath ? { executablePath } : {}),
  });
  await harness.start();
  try {
    const available = await harness.fillForm({
      form,
      subject: 'patient-1',
      content: { source: 'contact' },
    });
    if (available.errors.length) {
      throw new Error(`available read failed: ${JSON.stringify(available.errors)}`);
    }
    if (available.report.fields.st_date_of_birth_h !== '2024-03-05') {
      throw new Error(`contact value was not read: ${JSON.stringify(available.report.fields)}`);
    }

    await harness.clear();
    const missing = await harness.fillForm(
      {
        form,
        subject: {
          _id: 'patient-2',
          type: 'person',
          name: 'Child without DOB',
        },
        content: { source: 'contact' },
      },
      ['2023-11-17'],
    );
    if (missing.errors.length) {
      throw new Error(`fallback read failed: ${JSON.stringify(missing.errors)}`);
    }
    if (missing.report.fields.st_date_of_birth_h !== '2023-11-17') {
      throw new Error(`fallback value was not used: ${JSON.stringify(missing.report.fields)}`);
    }
    if (harness.consoleErrors.length) {
      throw new Error(`browser console errors: ${JSON.stringify(harness.consoleErrors)}`);
    }
  } finally {
    await harness.stop();
  }
}

main().catch(error => {
  console.error(error);
  process.exit(1);
});
