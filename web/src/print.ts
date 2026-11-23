// Print the converter's page layout (the 'html' output) with the browser's print dialog,
// where "Save as PDF" gives the Unicode PDF. The page carries its own @page size, fonts and
// pictures, and sets data-ready on <html> once its fonts are in and text is fitted.

let current: { frame: HTMLIFrameElement; url: string } | null = null;

function cleanup() {
  if (!current) return;
  current.frame.remove();
  URL.revokeObjectURL(current.url);
  current = null;
}

export async function printLayout(bytes: Uint8Array, title: string): Promise<void> {
  cleanup();
  const url = URL.createObjectURL(new Blob([bytes as BlobPart], { type: 'text/html' }));
  const frame = document.createElement('iframe');
  frame.title = title;
  // off screen but laid out at a normal size: the page measures its text before printing
  frame.style.cssText = 'position:fixed;left:-12000px;top:0;width:1200px;height:900px;border:0';
  frame.src = url;
  current = { frame, url };
  document.body.append(frame);

  await new Promise<void>((resolve, reject) => {
    const started = Date.now();
    const check = () => {
      const doc = frame.contentDocument;
      if (doc?.documentElement?.dataset.ready === '1') return resolve();
      if (Date.now() - started > 120_000) return reject(new Error('the page took too long to lay out'));
      setTimeout(check, 100);
    };
    frame.addEventListener('load', check, { once: true });
  });

  const win = frame.contentWindow!;
  // the print dialog suggests the document title as the file name
  win.document.title = title;
  win.focus();
  win.print();
}
