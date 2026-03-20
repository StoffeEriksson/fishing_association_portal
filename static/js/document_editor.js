document.addEventListener("DOMContentLoaded", function () {
  if (typeof tinymce === "undefined") return;

  const textarea = document.querySelector("#id_content");
  if (!textarea) return;

  tinymce.init({
    selector: "#id_content",
    height: 620,
    menubar: "file edit view insert format tools table help",
    plugins: "lists link table code help wordcount",
    toolbar:
      "undo redo | blocks | bold italic underline | " +
      "alignleft aligncenter alignright alignjustify | " +
      "bullist numlist outdent indent | table link | removeformat code",
    branding: false,
    promotion: false,
    statusbar: true,
    resize: true,
    content_style: `
      body {
        font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        font-size: 16px;
        line-height: 1.7;
        padding: 1rem;
      }
      h1,h2,h3,h4 { margin-top: 1.2rem; margin-bottom: 0.7rem; }
      p { margin: 0 0 0.9rem 0; }
      ul,ol { margin: 0 0 1rem 1.25rem; }
    `,
  });
});