const BOOK_JSON = "assets/哪一个很奇怪/book.json";

let BOOK_DIR = "";
let PAGE_FILES = [];
let GLOBAL_PRIORITY = "";
let GLOBAL_PRIORITY_TRAD = "";
let GLOBAL_NEW_WORDS = "";
let GLOBAL_NEW_WORDS_TRAD = "";
let charVariant = "trad";
let pages = [];
let currentPage = 0;

let cards = [];
let cardData = [];
let revealedCount = 0;
let priorityRevealed = 0;
let priorityTotal = 0;
let autoRevealing = false;

let reviewActive = false;
let reviewChars = [];
let reviewedIndices = new Set();

const dom = {};
function initDomCache() {
 ['cardsOverlay','emptyState','pageWrapper','bookPage','priorityText',
  'pageIndicator','prevBtn','nextBtn','editTitle','editImage','editText',
  'editPriority','editNewWords','editModal','reviewScreen','reviewGrid','reviewTitle',
  'reviewProgress','startReadingBtn','reviewBtn','resetBtn','revealBtn',
  'editBtn','editCancel','editSave'].forEach(id => dom[id] = document.getElementById(id));
}

function cleanChars(s) {
  return s.replace(/\s/g, '');
}

function getActivePriority() {
  return charVariant === 'trad' ? GLOBAL_PRIORITY_TRAD : GLOBAL_PRIORITY;
}

function getActiveNewWords() {
  return charVariant === 'trad' ? GLOBAL_NEW_WORDS_TRAD : GLOBAL_NEW_WORDS;
}

function getActiveChars(page) {
  return charVariant === 'trad' ? page.chars_trad : page.chars;
}

function getActiveLang() {
  return charVariant === 'trad' ? 'zh-TW' : 'zh-CN';
}

function computeCols(numChars, imgW, imgH) {
  if (numChars <= 0 || imgW <= 0 || imgH <= 0) return 1;
  const aspect = imgW / imgH;
  return Math.max(1, Math.round(Math.sqrt(numChars * aspect)));
}

async function loadBook() {
  try {
    const resp = await fetch(BOOK_JSON);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    BOOK_DIR = data.base;
    GLOBAL_PRIORITY = data.priority || "";
    GLOBAL_PRIORITY_TRAD = data.priority_trad || "";
    GLOBAL_NEW_WORDS = data.new_words || "";
    GLOBAL_NEW_WORDS_TRAD = data.new_words_trad || "";
    PAGE_FILES = data.pages.map(p => `page${p.page}.jpg`);
    pages = data.pages.map(p => ({
      chars: cleanChars(p.chars || ""),
      chars_trad: cleanChars(p.chars_trad || ""),
    }));
  } catch (err) {
    dom.emptyState.hidden = false;
    dom.emptyState.querySelector('p').textContent =
      `Could not load book data: ${err.message}. Check that book.json exists.`;
    dom.pageWrapper.style.visibility = 'hidden';
    dom.prevBtn.disabled = true;
    dom.nextBtn.disabled = true;
    dom.reviewBtn.disabled = true;
    dom.editBtn.disabled = true;
    dom.revealBtn.disabled = true;
    dom.resetBtn.disabled = true;
  }
}

function distributeChars(chars, numCols) {
  const total = chars.length;
  if (total === 0) return [];
  const baseCount = Math.floor(total / numCols);
  const extra = total % numCols;
  const columns = [];
  let idx = 0;
  for (let col = 0; col < numCols; col++) {
    const count = baseCount + (col < extra ? 1 : 0);
    columns.push(chars.slice(idx, idx + count).split(''));
    idx += count;
  }
  return columns;
}

function computePositions(columns) {
  const numCols = columns.length;
  if (numCols === 0) return [];
  const maxRows = Math.max(...columns.map(c => c.length));
  const colWidth = 1 / numCols;
  const rowHeight = 1 / maxRows;
  const positions = [];
  for (let col = 0; col < numCols; col++) {
    const x = (numCols - 1 - col) * colWidth;
    for (let row = 0; row < columns[col].length; row++) {
      const y = row * rowHeight;
      positions.push({
        char: columns[col][row],
        x, y, w: colWidth, h: rowHeight,
      });
    }
  }
  return positions;
}

function renderCards() {
  const overlay = dom.cardsOverlay;
  overlay.innerHTML = '';
  cards = [];
  cardData = [];
  revealedCount = 0;
  priorityRevealed = 0;

  const page = pages[currentPage];
  const activeChars = getActiveChars(page);
  const activePriority = getActivePriority();

  if (!activeChars) {
    dom.emptyState.hidden = false;
    dom.pageWrapper.style.visibility = 'hidden';
    updateProgress();
    return;
  }

  dom.emptyState.hidden = true;
  dom.pageWrapper.style.visibility = 'visible';

  const prioritySet = new Set(activePriority.split('').filter(c => activeChars.includes(c)));
  const newWordSet = new Set(getActiveNewWords().split('').filter(c => activeChars.includes(c)));
  priorityTotal = [...prioritySet].reduce((acc, c) =>
    acc + activeChars.split('').filter(ch => ch === c).length, 0);

  const img = dom.bookPage;
  const numCols = computeCols(activeChars.length, img.naturalWidth, img.naturalHeight);
  const columns = distributeChars(activeChars, numCols);
  const positions = computePositions(columns);

  positions.forEach((p, i) => {
    const isPriority = prioritySet.has(p.char);
    const isNewWord = newWordSet.has(p.char);
    const wrapper = document.createElement('div');
    wrapper.className = 'card-wrapper';
    wrapper.style.left = (p.x * 100) + '%';
    wrapper.style.top = (p.y * 100) + '%';
    wrapper.style.width = (p.w * 100) + '%';
    wrapper.style.height = (p.h * 100) + '%';
    wrapper.style.animationDelay = (i * 30) + 'ms';

    const face = document.createElement('div');
    face.className = 'card-face';
    face.textContent = p.char;
    wrapper.appendChild(face);

    const data = { wrapper, char: p.char, isPriority, isNewWord, index: i };
    cardData.push(data);

    wrapper.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      if (autoRevealing) return;
      toggleCard(data);
    });

    overlay.appendChild(wrapper);
    cards.push(wrapper);
  });

  updateProgress();
}

const UNICORN_ANIMATIONS = ['unicornBounce', 'unicornSpin', 'unicornWiggle', 'unicornPop', 'unicornGallop'];
const UNICORN_DURATION = 1100;

function showUnicorn(data) {
  const anim = UNICORN_ANIMATIONS[Math.floor(Math.random() * UNICORN_ANIMATIONS.length)];
  const overlay = document.createElement('div');
  overlay.className = 'unicorn-overlay';
  overlay.textContent = '🦄';
  overlay.style.animation = `${anim} ${UNICORN_DURATION}ms var(--ease) forwards`;
  data.wrapper.appendChild(overlay);
  setTimeout(() => overlay.remove(), UNICORN_DURATION);
}

function toggleCard(data) {
  const isRevealed = data.wrapper.classList.toggle('revealed');
  if (isRevealed) {
    revealedCount++;
    if (data.isPriority) priorityRevealed++;
    if (data.isNewWord) showUnicorn(data);
    if (navigator.vibrate) navigator.vibrate(10);
  } else {
    revealedCount = Math.max(0, revealedCount - 1);
    if (data.isPriority) priorityRevealed = Math.max(0, priorityRevealed - 1);
  }
  updateProgress();
  checkPriorityComplete();
}

function updateProgress() {
  const el = dom.priorityText;
  if (reviewActive) {
    el.textContent = "Review";
    el.classList.add('unset');
    dom.pageIndicator.textContent = "— / —";
    dom.prevBtn.disabled = true;
    dom.nextBtn.disabled = true;
    return;
  }
  const page = pages[currentPage];
  const activeChars = getActiveChars(page);
  if (!activeChars) {
    el.textContent = "Not set up";
    el.classList.add('unset');
  } else if (priorityTotal === 0) {
    el.textContent = "No priority";
    el.classList.add('unset');
  } else {
    el.textContent = `${priorityRevealed} / ${priorityTotal}`;
    el.classList.remove('unset');
  }

  dom.pageIndicator.textContent =
    `${currentPage + 1} / ${PAGE_FILES.length}`;
  dom.prevBtn.disabled = currentPage === 0;
  dom.nextBtn.disabled = currentPage === PAGE_FILES.length - 1;
}

function checkPriorityComplete() {
  if (priorityTotal > 0 && priorityRevealed === priorityTotal && revealedCount < cards.length && !autoRevealing) {
    autoRevealAll();
  }
}

function autoRevealAll() {
  autoRevealing = true;
  const unrevealed = cardData.filter(d => !d.wrapper.classList.contains('revealed'));
  const totalSteps = unrevealed.length;
  unrevealed.forEach((d, i) => {
    setTimeout(() => {
      d.wrapper.classList.add('revealed');
      revealedCount++;
      if (navigator.vibrate && i % 3 === 0) navigator.vibrate(8);
      updateProgress();
      if (i === totalSteps - 1) {
        autoRevealing = false;
        fadeAllCards();
      }
    }, i * 60);
  });
}

function revealAll() {
  const unrevealed = cardData.filter(d => !d.wrapper.classList.contains('revealed'));
  const totalSteps = unrevealed.length;
  unrevealed.forEach((d, i) => {
    setTimeout(() => {
      d.wrapper.classList.add('revealed');
      revealedCount++;
      if (d.isPriority) priorityRevealed++;
      if (navigator.vibrate && i % 3 === 0) navigator.vibrate(8);
      updateProgress();
      if (i === totalSteps - 1) {
        fadeAllCards();
      }
    }, i * 35);
  });
}

function fadeAllCards() {
  cardData.forEach((d, i) => {
    setTimeout(() => {
      d.wrapper.classList.add('faded');
    }, i * 40);
  });
}

function resetAll() {
  autoRevealing = false;
  cards.forEach(c => {
    c.classList.remove('revealed');
    c.classList.remove('faded');
    c.querySelectorAll('.unicorn-overlay').forEach(u => u.remove());
  });
  revealedCount = 0;
  priorityRevealed = 0;
  updateProgress();
}

function goToPage(idx) {
  if (idx < 0 || idx >= PAGE_FILES.length) return;
  autoRevealing = false;
  currentPage = idx;
  const img = dom.bookPage;
  img.onload = () => { img.onload = null; renderCards(); };
  img.src = `${BOOK_DIR}/${PAGE_FILES[idx]}`;
  if (img.complete) { img.onload = null; renderCards(); }
}

function nextPage() { goToPage(currentPage + 1); }
function prevPage() { goToPage(currentPage - 1); }

/* ---- Edit modal ---- */
function openEdit() {
  const page = pages[currentPage];
  const activeChars = getActiveChars(page);
  const activePriority = getActivePriority();
  const lang = getActiveLang();
  dom.editTitle.textContent =
    `Edit Page ${currentPage + 1}`;
  dom.editImage.src =
    `${BOOK_DIR}/${PAGE_FILES[currentPage]}`;
  dom.editText.value = activeChars;
  dom.editText.lang = lang;
  dom.editPriority.value = activePriority;
  dom.editPriority.lang = lang;
  dom.editNewWords.value = getActiveNewWords();
  dom.editNewWords.lang = lang;
  dom.editModal.classList.add('active');
  setTimeout(() => dom.editText.focus(), 250);
}

function closeEdit() {
  dom.editModal.classList.remove('active');
}

function saveEdit() {
  const text = cleanChars(dom.editText.value);
  const priority = cleanChars(dom.editPriority.value);
  const newWords = cleanChars(dom.editNewWords.value);
  const page = pages[currentPage];
  if (charVariant === 'trad') {
    page.chars_trad = text;
    GLOBAL_PRIORITY_TRAD = priority;
    GLOBAL_NEW_WORDS_TRAD = newWords;
  } else {
    page.chars = text;
    GLOBAL_PRIORITY = priority;
    GLOBAL_NEW_WORDS = newWords;
  }
  closeEdit();
  renderCards();
}

/* ---- Review screen ---- */
function renderReviewCards() {
  const grid = dom.reviewGrid;
  grid.innerHTML = '';
  reviewedIndices.clear();

  const priority = getActivePriority();
  const newWords = getActiveNewWords();
  const priorityChars = [...new Set(priority.split(''))];
  const newWordChars = [...new Set(newWords.split(''))].filter(c => !priorityChars.includes(c));
  reviewChars = [...priorityChars, ...newWordChars];

  dom.reviewTitle.textContent =
    charVariant === 'trad' ? '識字預習' : '识字预习';

  const newWordSet = new Set(newWordChars);

  reviewChars.forEach((char, i) => {
    const card = document.createElement('button');
    card.className = 'review-card';
    card.textContent = char;
    card.style.animationDelay = (i * 60) + 'ms';
    card.setAttribute('aria-label', `Character ${char}`);

    card.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      reviewCardTap(card, i);
    });

    grid.appendChild(card);
  });

  updateReviewProgress();
}

function reviewCardTap(card, idx) {
  if (navigator.vibrate) navigator.vibrate(10);
  card.classList.remove('popping');
  void card.offsetWidth;
  card.classList.add('popping');
  if (!reviewedIndices.has(idx)) {
    reviewedIndices.add(idx);
    card.classList.add('reviewed');
  }
  updateReviewProgress();
}

function updateReviewProgress() {
  const total = reviewChars.length;
  const reviewed = reviewedIndices.size;
  dom.reviewProgress.textContent = `${reviewed} / ${total}`;
  const startBtn = dom.startReadingBtn;
  if (reviewed === total && total > 0) {
    startBtn.classList.add('btn-primary');
  } else {
    startBtn.classList.remove('btn-primary');
  }
}

function showReview() {
  if (!getActivePriority() && !getActiveNewWords()) return;
  reviewActive = true;
  renderReviewCards();
  dom.reviewScreen.classList.add('active');
  updateProgress();
}

function hideReview() {
  reviewActive = false;
  dom.reviewScreen.classList.remove('active');
  updateProgress();
}

/* ---- Variant toggle ---- */
function toggleVariant(variant) {
  if (variant === charVariant) return;
  charVariant = variant;
  document.body.dataset.variant = variant;
  document.documentElement.lang = getActiveLang();
  document.querySelectorAll('.segmented-btn').forEach(btn => {
    const isActive = btn.dataset.variant === variant;
    btn.classList.toggle('active', isActive);
    btn.setAttribute('aria-pressed', isActive);
  });
  if (reviewActive) renderReviewCards();
  else if (PAGE_FILES.length) renderCards();
}

/* ---- Event listeners ---- */
initDomCache();
dom.prevBtn.addEventListener('click', prevPage);
dom.nextBtn.addEventListener('click', nextPage);
dom.resetBtn.addEventListener('click', resetAll);
dom.revealBtn.addEventListener('click', revealAll);
dom.editBtn.addEventListener('click', openEdit);
dom.editCancel.addEventListener('click', closeEdit);
dom.editSave.addEventListener('click', saveEdit);
dom.reviewBtn.addEventListener('click', showReview);
dom.startReadingBtn.addEventListener('click', hideReview);
document.querySelectorAll('.segmented-btn').forEach(btn => {
  btn.addEventListener('click', () => toggleVariant(btn.dataset.variant));
});
dom.editModal.addEventListener('click', (e) => {
  if (e.target === e.currentTarget) closeEdit();
});
document.addEventListener('keydown', (e) => {
  if (dom.editModal.classList.contains('active')) {
    if (e.key === 'Escape') closeEdit();
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') saveEdit();
    return;
  }
  if (e.key === 'Escape' && reviewActive) { hideReview(); return; }
  if (e.key === 'ArrowLeft') prevPage();
  if (e.key === 'ArrowRight') nextPage();
  if (e.key === 't' || e.key === 'T') toggleVariant(charVariant === 'trad' ? 'simp' : 'trad');
});

/* ---- Init ---- */
loadBook().then(() => {
  if (!PAGE_FILES.length) return;
  goToPage(0);
  const hasReviewContent = getActivePriority() || getActiveNewWords();
  dom.reviewBtn.disabled = !hasReviewContent;
  if (hasReviewContent) showReview();
});
