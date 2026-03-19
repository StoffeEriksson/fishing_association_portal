import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.4.168/pdf.min.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.4.168/pdf.worker.min.mjs";

const canvas = document.getElementById("pdf-canvas");

if (canvas) {
  let pdfDoc = null;
  let pageNum = 1;
  let scale = 1.2;

  const ctx = canvas.getContext("2d");
  const wrapper = document.getElementById("pdf-wrapper");
  const url = canvas.dataset.url;

  function renderPage(num) {
    pdfDoc.getPage(num).then(function (page) {
      const viewport = page.getViewport({ scale: scale });

      canvas.width = viewport.width;
      canvas.height = viewport.height;

      const renderContext = {
        canvasContext: ctx,
        viewport: viewport,
      };

      page.render(renderContext);
      document.getElementById("page-num").textContent = num;
      document.getElementById("page-count").textContent = pdfDoc.numPages;
    });
  }

  pdfjsLib.getDocument(url).promise
    .then(function (pdf) {
      pdfDoc = pdf;
      renderPage(pageNum);
    })
    .catch(function (error) {
      if (wrapper) {
        wrapper.innerHTML = `
          <div class="py-5 text-center">
            <div class="mb-3">Kunde inte visa PDF</div>
            <a href="${url}" target="_blank" class="btn btn-dark">Öppna PDF</a>
          </div>
        `;
      }
      console.error(error);
    });

  document.getElementById("prev-page")?.addEventListener("click", function () {
    if (!pdfDoc || pageNum <= 1) return;
    pageNum--;
    renderPage(pageNum);
  });

  document.getElementById("next-page")?.addEventListener("click", function () {
    if (!pdfDoc || pageNum >= pdfDoc.numPages) return;
    pageNum++;
    renderPage(pageNum);
  });

  document.getElementById("zoom-in")?.addEventListener("click", function () {
    if (!pdfDoc) return;
    scale = Math.min(scale + 0.2, 3);
    renderPage(pageNum);
  });

  document.getElementById("zoom-out")?.addEventListener("click", function () {
    if (!pdfDoc) return;
    scale = Math.max(scale - 0.2, 0.6);
    renderPage(pageNum);
  });
}