'use strict';

const $ = id => document.getElementById(id);

let selected = null;
let current = null;
let result = null;
let timer = null;
let pollVersion = 0;
let revealResult = false;

const languages = {
  zh: '中文',
  en: '英文',
  ja: '日文',
  ko: '韓文',
  auto: '自動偵測'
};


const time = seconds => {

  const value =
    Math.max(
      0,
      Math.floor(seconds)
    );

  return [
    Math.floor(
      value / 3600
    ),
    Math.floor(
      value / 60
    ) % 60,
    value % 60
  ]
    .map(
      n =>
        String(n)
          .padStart(
            2,
            '0'
          )
    )
    .join(':');
};


/* =========================================================
   Local Storage
   ========================================================= */

function remember(id) {

  try {

    if (id) {

      localStorage.setItem(
        'whisper-job',
        id
      );

    } else {

      localStorage.removeItem(
        'whisper-job'
      );
    }

  } catch {

    // localStorage 不可用時不影響主要功能。

  }
}


/* =========================================================
   API
   ========================================================= */

async function api(
  url,
  options = {}
) {

  const response =
    await fetch(
      url,
      options
    );


  if (!response.ok) {

    const error =
      await response
        .json()
        .catch(
          () => ({
            detail:
              '連線失敗'
          })
        );


    const failure =
      Error(
        typeof error.detail ===
        'string'
          ? error.detail
          : '請確認輸入內容後重試。'
      );


    failure.status =
      response.status;


    throw failure;
  }


  return response.json();
}


/* =========================================================
   Progress
   ========================================================= */

function setProgress({
  state = 'idle',
  stage,
  value = null,
  detail = '',
  warning = '',
  file = '',
  heading
}) {

  const labels = {
    idle:
      'READY',

    uploading:
      'UPLOADING',

    queued:
      'QUEUED',

    running:
      'PROCESSING',

    done:
      'COMPLETE',

    error:
      'ERROR'
  };


  $('progress').hidden =
    false;


  $('progress').dataset.state =
    state;


  $('process-state').textContent =
    labels[state]
      ? labels[state]
      : 'PROCESSING';


  const defaultHeading = {
    idle:
      'READY TO\nLISTEN.',

    uploading:
      'UPLOADING\nSOURCE.',

    done:
      'TRANSCRIPT\nREADY.',

    error:
      'PLEASE\nTRY AGAIN.'
  }[state];


  if (heading) {

    $('process-heading').textContent =
      heading;

  } else if (defaultHeading) {

    $('process-heading').textContent =
      defaultHeading;

  } else {

    $('process-heading').textContent =
      'TRANSCRIBING\nAUDIO.';
  }


  const measurable =
    Number.isFinite(
      value
    );


  const percent =
    measurable
      ? Math.min(
          100,
          Math.max(
            0,
            Math.floor(
              value
            )
          )
        )
      : null;


  $('progress-number').textContent =
    measurable
      ? String(percent)
      : '—';


  if (measurable) {

    const suffix =
      document.createElement(
        'small'
      );

    suffix.textContent =
      '%';

    $('progress-number')
      .append(
        suffix
      );
  }


  $('bar').hidden =
    !measurable;


  $('bar').value =
    percent !== null
      ? percent
      : 0;


  $('stage').textContent =
    stage;


  if (
    state ===
    'error'
  ) {

    $('percent').textContent =
      '請確認檔案與服務狀態後再試。';

  } else if (
    measurable
  ) {

    $('percent').textContent =
      detail
        ? detail
        : '依實際處理進度更新。';

  } else {

    $('percent').textContent =
      detail
        ? detail
        : '此階段無法計算百分比。';
  }


  $('process-file').textContent =
    file;


  $('warning').textContent =
    warning;


  $('warning').hidden =
    !warning;
}


/* =========================================================
   File Selection
   ========================================================= */

function choose(file) {

  if (!file) {
    return;
  }


  selected =
    file;


  $('filename').textContent =
    file.name +
    ' · ' +
    (
      file.size /
      1024 /
      1024
    ).toFixed(1) +
    ' MB';


  $('drop').classList.add(
    'has-file'
  );


  $('start').disabled =
    false;
}


$('file').onchange =
  event => {

    choose(
      event.target.files[0]
    );
  };


$('drop').onclick =
  () => {

    $('file').click();
  };


/* =========================================================
   Drag & Drop
   ========================================================= */

let dragDepth = 0;


$('drop').addEventListener(
  'dragenter',
  event => {

    event.preventDefault();

    dragDepth++;

    $('drop')
      .classList
      .add(
        'over'
      );
  }
);


$('drop').addEventListener(
  'dragover',
  event => {

    event.preventDefault();

    event.dataTransfer.dropEffect =
      'copy';
  }
);


$('drop').addEventListener(
  'dragleave',
  event => {

    event.preventDefault();

    dragDepth--;

    if (
      dragDepth <= 0
    ) {

      dragDepth = 0;

      $('drop')
        .classList
        .remove(
          'over'
        );
    }
  }
);


$('drop').addEventListener(
  'drop',
  event => {

    event.preventDefault();

    dragDepth = 0;

    $('drop')
      .classList
      .remove(
        'over'
      );

    choose(
      event.dataTransfer.files[0]
    );
  }
);


/* =========================================================
   Start
   ========================================================= */

$('start').onclick =
  () => {

    if (!selected) {
      return;
    }


    clearTimeout(
      timer
    );


    pollVersion++;


    current =
      null;

    result =
      null;


    $('player').pause();


    $('player')
      .removeAttribute(
        'src'
      );


    $('player').load();


    $('start').disabled =
      true;


    $('result').hidden =
      true;


    revealResult =
      true;


    const file =
      selected;


    setProgress({
      state:
        'uploading',

      stage:
        '正在上傳',

      value:
        0,

      file:
        file.name,

      detail:
        '正在傳送至本機服務。'
    });


    const query =
      new URLSearchParams({
        filename:
          file.name,

        language:
          $('language').value,

        traditional:
          $('traditional').checked,

        model:
          $('model').value,

        processing_mode:
          $('processing_mode').value
      });


    const xhr =
      new XMLHttpRequest();


    xhr.open(
      'POST',
      '/api/jobs?' +
      query
    );


    if (file.type) {

      xhr.setRequestHeader(
        'Content-Type',
        file.type
      );

    } else {

      xhr.setRequestHeader(
        'Content-Type',
        'application/octet-stream'
      );
    }


    xhr.setRequestHeader(
      'X-Local-Request',
      '1'
    );


    xhr.upload.onprogress =
      event => {

        if (
          !event.lengthComputable
        ) {
          return;
        }


        setProgress({
          state:
            'uploading',

          stage:
            '正在上傳',

          value:
            event.loaded /
            event.total *
            100,

          file:
            file.name,

          detail:
            '上傳 ' +
            (
              event.loaded /
              1024 /
              1024
            ).toFixed(1) +
            ' / ' +
            (
              event.total /
              1024 /
              1024
            ).toFixed(1) +
            ' MB'
        });
      };


    xhr.onload =
      () => {

        if (
          xhr.status ===
          202
        ) {

          current =
            JSON.parse(
              xhr.responseText
            ).id;


          remember(
            current
          );


          pollVersion++;


          poll();


          return;
        }


        let message =
          '上傳失敗，請稍後重試。';


        try {

          const detail =
            JSON.parse(
              xhr.responseText
            ).detail;


          if (
            typeof detail ===
            'string'
          ) {

            message =
              detail;
          }

        } catch {

          // Ignore invalid JSON.

        }


        setProgress({
          state:
            'error',

          stage:
            message,

          file:
            file.name
        });


        $('start').disabled =
          false;
      };


    xhr.onerror =
      () => {

        setProgress({
          state:
            'error',

          stage:
            '連線中斷，請確認程式仍在執行。',

          file:
            file.name
        });


        $('start').disabled =
          false;
      };


    xhr.send(
      file
    );


    $('progress')
      .scrollIntoView({
        behavior:
          matchMedia(
            '(prefers-reduced-motion: reduce)'
          ).matches
            ? 'auto'
            : 'smooth',

        block:
          'start'
      });
  };


/* =========================================================
   Job Heading
   ========================================================= */

function jobHeading(job) {

  if (
    job.status ===
    'done'
  ) {

    return (
      'TRANSCRIPT\nREADY.'
    );
  }


  if (
    job.status ===
    'error'
  ) {

    return (
      'PLEASE\nTRY AGAIN.'
    );
  }


  if (
    job.status ===
    'queued'
  ) {

    return (
      'IN THE\nQUEUE.'
    );
  }


  if (
    job.stage.includes(
      '下載'
    )
  ) {

    return (
      'DOWNLOADING\nMODEL.'
    );
  }


  if (
    job.stage.includes(
      '載入'
    )
  ) {

    return (
      'LOADING\nMODEL.'
    );
  }


  if (
    job.stage.includes(
      '準備'
    )
    ||
    job.stage.includes(
      '相容'
    )
  ) {

    return (
      'PREPARING\nAUDIO.'
    );
  }


  return (
    'TRANSCRIBING\nAUDIO.'
  );
}


/* =========================================================
   Poll
   ========================================================= */

async function poll() {

  const pollingId =
    current;


  const version =
    pollVersion;


  if (!pollingId) {
    return;
  }


  try {

    const job =
      await api(
        '/api/jobs/' +
        pollingId
      );


    if (
      current !==
        pollingId
      ||
      version !==
        pollVersion
    ) {

      return;
    }


    const measurable =
      job.duration > 0
      &&
      (
        job.stage ===
          '正在辨識'
        ||
        job.status ===
          'done'
      );


    setProgress({
      state:
        job.status,

      stage:
        job.stage,

      heading:
        jobHeading(
          job
        ),

      file:
        job.file,

      value:
        measurable
          ? (
              job.processed /
              job.duration *
              100
            )
          : null,

      warning:
        job.warning
          ? job.warning
          : '',

      detail:
        measurable
          ? (
              '已處理 ' +
              time(
                job.processed
              ) +
              ' / ' +
              time(
                job.duration
              ) +
              '（依時間碼估算）'
            )
          : ''
    });


    if (
      job.status ===
      'done'
    ) {

      const loaded =
        await api(
          '/api/jobs/' +
          pollingId +
          '/result'
        );


      if (
        current !==
          pollingId
        ||
        version !==
          pollVersion
      ) {

        return;
      }


      result =
        loaded;


      show();


      $('start').disabled =
        !selected;


      return;
    }


    if (
      job.status ===
      'error'
    ) {

      $('start').disabled =
        !selected;

      return;
    }


    timer =
      setTimeout(
        poll,
        1500
      );

  } catch (error) {


    if (
      current !==
        pollingId
      ||
      version !==
        pollVersion
    ) {

      return;
    }


    if (
      error.status ===
      404
    ) {

      current =
        null;

      result =
        null;


      remember(
        null
      );


      $('result').hidden =
        true;


      $('start').disabled =
        !selected;


      setProgress({
        state:
          'idle',

        stage:
          '上次結果已清除，請重新上傳辨識。'
      });


      return;
    }


    setProgress({
      state:
        'error',

      stage:
        error.message +
        '；3 秒後重試。'
    });


    timer =
      setTimeout(
        poll,
        3000
      );
  }
}


/* =========================================================
   Transcript Download Link
   ========================================================= */

function createDownloadLink(
  format,
  label
) {

  const link =
    document.createElement(
      'a'
    );


  link.href =
    '/api/jobs/' +
    current +
    '/download/' +
    format;


  link.setAttribute(
    'aria-label',
    '下載 ' +
    label
  );


  link.textContent =
    label;


  const arrow =
    document.createElement(
      'span'
    );


  arrow.textContent =
    '↗';


  arrow.setAttribute(
    'aria-hidden',
    'true'
  );


  link.append(
    arrow
  );


  return link;
}


/* =========================================================
   Audio Download Link
   ========================================================= */

function createAudioDownloadLink() {

  const link =
    document.createElement(
      'a'
    );


  /*
   * 重要：
   *
   * 音檔不再經過
   * /download/{format}
   *
   * 而是直接走獨立 API：
   *
   * /download-audio
   */

  link.href =
    '/api/jobs/' +
    current +
    '/download-audio';


  link.setAttribute(
    'aria-label',
    '下載增強音檔 WAV'
  );


  link.textContent =
    '增強音檔 WAV';


  const arrow =
    document.createElement(
      'span'
    );


  arrow.textContent =
    '↗';


  arrow.setAttribute(
    'aria-hidden',
    'true'
  );


  link.append(
    arrow
  );


  return link;
}


/* =========================================================
   Show Result
   ========================================================= */

function show() {

  $('result').hidden =
    false;


  $('result-file').textContent =
    result.file;


  $('result-count').textContent =
    String(
      result.subtitles.length
    ).padStart(
      2,
      '0'
    );


  $('result-duration').textContent =
    time(
      result.duration
    );


  $('metadata').textContent =
    '處理時間 ' +
    result.processing_seconds
      .toFixed(1) +
    ' 秒 · 原始字詞時間碼已保留';


  if (
    languages[
      result.language
    ]
  ) {

    $('result-language').textContent =
      languages[
        result.language
      ];

  } else {

    $('result-language').textContent =
      result.language;
  }


  $('result-compute').textContent =
    result.device
      .toUpperCase() +
    ' / ' +
    result.compute_type;


  $('result-rtf').textContent =
    result.real_time_factor
      .toPrecision(3);


  $('copy-status').textContent =
    '';


  $('copy-fallback').hidden =
    true;


  $('player-note').textContent =
    '點擊逐字稿時間碼，跳到對應位置。';


  $('player').src =
    '/api/jobs/' +
    current +
    '/media';


  /* =======================================================
     Downloads
     ======================================================= */

  $('downloads')
    .replaceChildren();


  const transcriptDownloads = [
    [
      'srt',
      'SRT'
    ],
    [
      'txt',
      'TXT'
    ],
    [
      'timed.txt',
      '帶時間碼 TXT'
    ],
    [
      'vtt',
      'VTT'
    ],
    [
      'json',
      'JSON'
    ]
  ];


  for (
    const [
      format,
      label
    ]
    of transcriptDownloads
  ) {

    const link =
      createDownloadLink(
        format,
        label
      );


    $('downloads')
      .append(
        link
      );
  }


  /*
   * WAV 使用完全獨立 API
   */

  const audioLink =
    createAudioDownloadLink();


  $('downloads')
    .append(
      audioLink
    );


  $('search').value =
    '';


  render();


  if (
    revealResult
  ) {

    revealResult =
      false;


    $('result')
      .scrollIntoView({
        behavior:
          matchMedia(
            '(prefers-reduced-motion: reduce)'
          ).matches
            ? 'auto'
            : 'smooth',

        block:
          'start'
      });
  }
}


/* =========================================================
   Render Transcript
   ========================================================= */

function render() {

  const query =
    $('search')
      .value
      .trim()
      .toLocaleLowerCase();


  const fragment =
    document.createDocumentFragment();


  let count =
    0;


  const dataSource =
    (
      result.processing_mode ===
      'dual_track'
      &&
      Array.isArray(
        result.segments
      )
    )
      ? result.segments
      : result.subtitles;


  for (
    const cue
    of dataSource
  ) {

    let displayText =
      cue.text || '';


    if (
      cue.display_text
    ) {

      displayText =
        cue.display_text;
    }


    if (
      query
      &&
      !displayText
        .toLocaleLowerCase()
        .includes(
          query
        )
    ) {

      continue;
    }


    count++;


    const segment =
      document.createElement(
        'div'
      );


    segment.className =
      'segment';


    let startVal =
      0;


    if (
      cue.start !==
      undefined
    ) {

      startVal =
        cue.start;

    } else if (
      cue.start_time !==
      undefined
    ) {

      startVal =
        cue.start_time;
    }


    let endVal =
      0;


    if (
      cue.end !==
      undefined
    ) {

      endVal =
        cue.end;

    } else if (
      cue.end_time !==
      undefined
    ) {

      endVal =
        cue.end_time;
    }


    segment.dataset.start =
      startVal;


    segment.dataset.end =
      endVal;


    const button =
      document.createElement(
        'button'
      );


    button.type =
      'button';


    button.textContent =
      time(
        startVal
      );


    button.setAttribute(
      'aria-label',
      '播放 ' +
      time(
        startVal
      ) +
      ' 至 ' +
      time(
        endVal
      )
    );


    const end =
      document.createElement(
        'small'
      );


    end.textContent =
      '→ ' +
      time(
        endVal
      );


    button.append(
      end
    );


    button.onclick =
      () => {

        $('player').currentTime =
          Number(
            startVal
          );


        $('player')
          .play()
          .catch(
            () => {}
          );
      };


    const text =
      document.createElement(
        'p'
      );


    text.textContent =
      displayText;


    segment.append(
      button,
      text
    );


    /* =====================================================
       Dual Track Difference
       ===================================================== */

    if (
      cue.status ===
      'LOW_CONFIDENCE'
    ) {

      segment.style.borderLeft =
        '3px solid #FF5820';


      segment.style.backgroundColor =
        'rgba(255, 88, 32, 0.05)';


      segment.style.paddingLeft =
        '12px';


      const diffBox =
        document.createElement(
          'div'
        );


      diffBox.style.fontSize =
        '0.85em';


      diffBox.style.marginTop =
        '8px';


      diffBox.style.padding =
        '10px';


      diffBox.style.backgroundColor =
        'rgba(255, 88, 32, 0.1)';


      diffBox.style.borderRadius =
        '4px';


      const diffTitle =
        document.createElement(
          'strong'
        );


      diffTitle.textContent =
        `⚠️ 語意差異需確認 (${
          cue.difference_type ===
          'CRITICAL_DIFFERENCE'
            ? '關鍵字不一致'
            : '一般差異'
        })`;


      diffTitle.style.display =
        'block';


      diffTitle.style.marginBottom =
        '6px';


      diffTitle.style.color =
        '#FF5820';


      const textA =
        document.createElement(
          'div'
        );


      textA.textContent =
        `增強軌 (A): ${
          cue.transcript_a
            ? cue.transcript_a
            : ''
        }`;


      textA.style.marginBottom =
        '2px';


      const textB =
        document.createElement(
          'div'
        );


      textB.textContent =
        `原始軌 (B): ${
          cue.transcript_b
            ? cue.transcript_b
            : ''
        }`;


      textB.style.color =
        'var(--text-muted)';


      diffBox.append(
        diffTitle,
        textA,
        textB
      );


      segment.append(
        diffBox
      );
    }


    fragment.append(
      segment
    );
  }


  $('transcript')
    .replaceChildren(
      fragment
    );


  $('search-count').textContent =
    query
      ? (
          count +
          ' 個符合段落 / 共 ' +
          dataSource.length +
          ' 段'
        )
      : (
          dataSource.length +
          ' 段 · 點時間碼回到原音'
        );


  if (!count) {

    const empty =
      document.createElement(
        'p'
      );


    empty.className =
      'empty-state';


    empty.textContent =
      query
        ? '找不到相符段落。試試其他關鍵字。'
        : '沒有偵測到語音。';


    $('transcript')
      .append(
        empty
      );
  }


  highlight();
}


/* =========================================================
   Highlight
   ========================================================= */

function highlight() {

  const position =
    $('player').currentTime;


  for (
    const element
    of $('transcript')
      .querySelectorAll(
        '.segment'
      )
  ) {

    const active =
      position >=
        Number(
          element.dataset.start
        )
      &&
      position <
        Number(
          element.dataset.end
        );


    element.classList.toggle(
      'active',
      active
    );


    const button =
      element.querySelector(
        'button'
      );


    if (!button) {
      continue;
    }


    if (active) {

      button.setAttribute(
        'aria-current',
        'true'
      );

    } else {

      button.removeAttribute(
        'aria-current'
      );
    }
  }
}


/* =========================================================
   Search
   ========================================================= */

$('search').oninput =
  () => {

    if (result) {
      render();
    }
  };


/* =========================================================
   Player
   ========================================================= */

$('player').ontimeupdate =
  highlight;


$('player').onerror =
  () => {

    if (
      !current
      ||
      !result
    ) {

      return;
    }


    if (
      !$('player')
        .src
        .endsWith(
          '/preview'
        )
    ) {

      $('player').src =
        '/api/jobs/' +
        current +
        '/preview';


      $('player-note').textContent =
        '原始編碼無法在瀏覽器播放，已切換相容音訊；時間碼跳轉仍可使用。';


      return;
    }


    $('player-note').textContent =
      '相容音訊播放失敗，請使用本機播放器。';
  };


/* =========================================================
   Copy
   ========================================================= */

$('copy').onclick =
  async () => {

    if (!result) {
      return;
    }


    const text =
      result.subtitles
        .map(
          cue =>
            cue.text
              .trim()
        )
        .join(
          '\n\n'
        );


    try {

      await navigator
        .clipboard
        .writeText(
          text
        );


      $('copy-status').textContent =
        '已複製全部逐字稿。';

    } catch {

      const fallback =
        $('copy-fallback');


      fallback.hidden =
        false;


      fallback.value =
        text;


      fallback.focus();


      fallback.select();


      let copied =
        false;


      try {

        copied =
          document.execCommand(
            'copy'
          );

      } catch {

        copied =
          false;
      }


      $('copy-status').textContent =
        copied
          ? '已複製全部逐字稿。'
          : '請按 Ctrl+C 複製已選取文字。';


      if (copied) {

        fallback.hidden =
          true;


        $('copy').focus();
      }
    }
  };


/* =========================================================
   System
   ========================================================= */

api(
  '/api/system'
)
  .then(
    system => {

      $('system-summary').textContent =
        system.gpu;


      const version =
        system.backend_version
          ? (
              ' · Backend ' +
              system.backend_version
            )
          : '';


      $('hardware').textContent =
        system.gpu +
        ' · VRAM ' +
        system.vram +
        ' · CUDA ' +
        (
          system.cuda
            ? '可用（實際模型載入時再驗證）'
            : '未就緒，可能降級 CPU'
        ) +
        ' · large-v3 · float16' +
        version;
    }
  )
  .catch(
    error => {

      $('system-summary').textContent =
        '無法讀取環境';


      $('hardware').textContent =
        error.message;
    }
  );


/* =========================================================
   Restore Previous Job
   ========================================================= */

try {

  current =
    localStorage.getItem(
      'whisper-job'
    );

} catch {

  current =
    null;
}


if (current) {

  const restored =
    current;


  api(
    '/api/jobs/' +
    restored
  )
    .then(
      () => {

        if (
          current ===
          restored
        ) {

          poll();
        }
      }
    )
    .catch(
      () => {

        if (
          current ===
          restored
        ) {

          current =
            null;


          remember(
            null
          );
        }
      }
    );
}