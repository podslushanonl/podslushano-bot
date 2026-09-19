(() => {
  const guideStep = document.querySelector('.step[data-step="guide"]');
  const form = document.getElementById('bookingForm');
  if (!guideStep || !form || document.getElementById('guidePhoto')) return;

  const note = guideStep.querySelector('.small-note');
  const field = document.createElement('div');
  field.className = 'field';
  field.innerHTML = `
    <span>Фото или логотип <b>обязательно для Premium</b></span>
    <input id="guidePhoto" type="file" accept="image/jpeg,image/png">
    <div id="guidePhotoStatus" class="small-note">JPG или PNG. Изображение автоматически оптимизируется перед оплатой.</div>
    <img id="guidePhotoPreview" alt="Предпросмотр фото Contact Guide" style="display:none;width:112px;height:112px;object-fit:cover;border-radius:14px;border:1px solid #d8d2c8;margin-top:8px">
  `;
  if (note) {
    note.before(field);
    note.textContent = 'Фото/логотип, бейдж 🌟 и приоритет в выдаче входят в Premium на 2 месяца.';
  } else {
    guideStep.appendChild(field);
  }

  const input = document.getElementById('guidePhoto');
  const status = document.getElementById('guidePhotoStatus');
  const preview = document.getElementById('guidePhotoPreview');
  let photo = null;
  let processing = false;

  function fileToDataUrl(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  function imageFromUrl(url) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = reject;
      img.src = url;
    });
  }

  function canvasBlob(canvas, quality) {
    return new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', quality));
  }

  async function optimise(file) {
    if (!['image/jpeg', 'image/png'].includes(file.type)) {
      throw new Error('Загрузите JPG или PNG.');
    }
    if (file.size > 12 * 1024 * 1024) {
      throw new Error('Исходный файл слишком большой. Максимум 12 МБ.');
    }

    // Small files can stay untouched, preserving PNG transparency/logos.
    if (file.size <= 380000) {
      const dataUrl = await fileToDataUrl(file);
      return {mime: file.type, b64: dataUrl.split(',')[1], dataUrl};
    }

    const objectUrl = URL.createObjectURL(file);
    try {
      const img = await imageFromUrl(objectUrl);
      const maxSide = 1200;
      const scale = Math.min(1, maxSide / Math.max(img.naturalWidth, img.naturalHeight));
      const width = Math.max(1, Math.round(img.naturalWidth * scale));
      const height = Math.max(1, Math.round(img.naturalHeight * scale));
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, width, height);
      ctx.drawImage(img, 0, 0, width, height);

      let blob = null;
      for (const quality of [0.84, 0.74, 0.64, 0.54]) {
        blob = await canvasBlob(canvas, quality);
        if (blob && blob.size <= 450000) break;
      }
      if (!blob || blob.size > 520000) {
        throw new Error('Не удалось уменьшить изображение. Выберите другое фото.');
      }
      const dataUrl = await fileToDataUrl(blob);
      return {mime: 'image/jpeg', b64: dataUrl.split(',')[1], dataUrl};
    } finally {
      URL.revokeObjectURL(objectUrl);
    }
  }

  input.addEventListener('change', async () => {
    photo = null;
    preview.style.display = 'none';
    const file = input.files && input.files[0];
    if (!file) {
      status.textContent = 'JPG или PNG. Изображение обязательно для Premium.';
      return;
    }
    processing = true;
    input.disabled = true;
    status.textContent = 'Подготавливаем изображение…';
    try {
      photo = await optimise(file);
      preview.src = photo.dataUrl;
      preview.style.display = 'block';
      status.textContent = '✓ Фото готово и будет добавлено в Premium-карточку.';
      if (typeof hideErr === 'function') hideErr('guideError');
    } catch (error) {
      photo = null;
      input.value = '';
      status.textContent = error && error.message ? error.message : 'Не удалось обработать изображение.';
      if (typeof showErr === 'function') showErr('guideError', status.textContent);
    } finally {
      processing = false;
      input.disabled = false;
    }
  });

  const previousValidateGuide = window.validateGuide;
  window.validateGuide = function () {
    if (typeof previousValidateGuide === 'function' && !previousValidateGuide()) return false;
    if (processing) {
      showErr('guideError', 'Подождите, пока фото закончит обрабатываться.');
      return false;
    }
    if (!photo || !photo.b64) {
      showErr('guideError', 'Добавьте фото или логотип — это обязательная часть Premium-карточки.');
      return false;
    }
    hideErr('guideError');
    return true;
  };

  window.buildPhonePayload = function () {
    const phone = document.getElementById('billingPhone').value.trim();
    if (productId !== 'ad_campaign') return phone;
    const guide = {
      name: document.getElementById('guideName').value.trim(),
      category: document.getElementById('guideCategory').value,
      online: document.getElementById('guideOnline').checked,
      city: document.getElementById('guideCity').value.trim(),
      description: document.getElementById('guideDescription').value.trim(),
      contact: document.getElementById('guideContact').value.trim(),
      photo_b64: photo ? photo.b64 : '',
      photo_mime: photo ? photo.mime : ''
    };
    return phone + '|||GUIDE64:' + encodeGuide(guide);
  };
})();
