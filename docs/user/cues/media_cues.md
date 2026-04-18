# Media cues

```{toctree}
:hidden:

media_custom_elements
```

Media cues provide playback capabilities. Thanks to GStreamer we support a very wide range of media formats,
and a variety of effects can be applied at runtime without modification to the source files.

LiSP supports three types of media cues:

* **Audio cues** — playback of audio files
* **Video cues** — playback of video files with audio, displayed in a projection window
* **Image cues** — display of still images for a configurable duration

## Audio Cues

Audio cues allow you to play back audio files.

### Options

When editing a media cue options, two sections (tabs) are provided,
one (`Media Cue`) has a few common options, while the second (`Media Settings`) 
provides fine-grained control on the multimedia source, output and applied effects.

```{image} ../_static/media_cue_options_tab.png
:alt: Media Cue option tabs
```

#### Media Cue

* **Start time:** Start position of the media
* **Stop time:** End position of the media
* **Loop:** Number of repetitions after first play (-1 is infinite)

Start/End time allow you to trim the media file without modifications, keep in mind that the UI will keep showing the
original file duration independently of these options.

Loops allow to replay the same media multiple times, they _should_ be seamless if the media content is seamless 
and depending on the media format, `.wav` are usually a safe option.<br>
Loops can be stopped "artificially" via a `Loop Release` action.

#### Media Settings

Each media cue is made of a sequence of elements, referred as "pipeline":

* One "input"
* Any number of "plugins" or "effects"
* One "output"

In this section both, the pipeline composition and each element options can be controlled.

```{image} ../_static/media_cue_media_settings.png
:alt: Media Settings
:align: center
```

Active elements can be changed using the **Change Pipeline** button (bottom left)

```{image} ../_static/media_cue_edit_pipeline.png
:alt: Edit pipeline
:align: center
```

```{note}
The default pipeline composition can be changed via `File > Preferences > Plugins > GStreamer`, and will apply on news cues.
```

```{note}
While editing multiple media cues at once, it's necessary to _Change Pipeline_ to select the elements to update.<br>
The pipeline itself cannot be canged in this mode.
```

## Video Cues

Video cues play back video files with audio. The video is displayed in a dedicated projection window
while the audio plays through the configured output device. Video cues support all the same
controls as audio cues: start, stop, pause, resume, seek, loop, and fading.

To add a video cue, use `Edit > Media cues > Video cue (from file)` or ``[CTRL+SHIFT+M]``.
You can also drag and drop video files directly into the layout — LiSP automatically
detects the file type and creates the correct cue.

### Video Output Window

Video is displayed in a separate borderless projection window. This window can be moved to a
secondary display for projection. Key features:

* **Fullscreen mode** on the target display
* **Mouse cursor** is hidden automatically during fullscreen playback
* **Black between cues** — the window shows a black screen when no video is playing
* The window appears automatically when video or image cues are added to the session

### Video Fading

Video cues support fade-to-black via the **Video Alpha** pipeline element. When a video cue
has both `Volume` and `VideoAlpha` in its pipeline, fade operations affect both audio and video
simultaneously — audio fades to silence while video fades to black.

### Video Monitor

A small floating confidence monitor window mirrors the projection output on the operator's
primary screen. This is useful when the operator cannot see the projection surface directly.

Toggle via `Tools > Video Monitor`.

## Image Cues

Image cues display still images (JPEG, PNG, BMP, SVG, TIFF, WebP) in the projection window
for a configurable duration. When the duration expires, the cue ends automatically.

To add an image cue, use `Edit > Media cues > Image cue (from file)` or ``[CTRL+SHIFT+I]``.

### Slideshows

To create a slideshow, add multiple image cues and group them into a **Group Cue** in
**Playlist** mode. Each image displays for its configured duration, then the next image
starts automatically. You can also set a crossfade duration on the group for smooth
transitions between images.

To combine a slideshow with background music, place the audio cue and the slideshow group
into another Group Cue in **Parallel** mode — both start simultaneously.

### Options (Image Settings)

* **Source:** the image file path
* **Duration:** how long to display the image (in milliseconds, default 5000ms)

```{note}
Image cues have no audio output. The pipeline contains only a video output element.
Looping is not supported for individual image cues — use a Group Cue in playlist mode
with loop enabled instead.
```

## Inputs

### URI Input

Read and decode data from a file, local or remote (e.g. http, https, etc..)

* **Source:** the URI to look for data (a "find file" button is provided for searching local files)

### URI A/V Input

Read and decode audio and video data from a file. Used automatically for video cues.
The element routes audio and video streams to their respective pipeline branches.

* **Source:** the URI to the video file

Audio-only files played through this input work correctly — the unused video branch is
removed automatically. Similarly, video-only files (no audio track) are handled gracefully.

### Image Input

Read and decode a still image file, converting it into a continuous video stream using
GStreamer's `imagefreeze` element. Used automatically for image cues.

* **Source:** the image file path
* **Duration:** display duration in milliseconds (default 5000ms)

### System Input

Get the audio from the system-default input device (e.g. microphone), no option is provided

```{note}
To use `System Input` you need to create a media cue with a file, and then change the source element.
```

## Effect/Plugins

Used for audio-processing or data-probing, in some case the order affect the results

### Volume

Allow to change the volume level, or mute the media.

* **Volume:** volume level in dB (can be muted)
* **Normalized Volume:** parameter used by other components (e.g. ReplayGain) to
  normalize the volume level without affecting user values, you can only reset the value (to 0dB).

### 10 Bands Equalizer

Allow to equalize the media with 10 frequency bands [30Hz-15KHz].

### dB Meter

Allow external components to get the current sound level, used for UI visualization.

* **Time between levels:** millisecond between one extracted value and the next (_lower values will increase CPU usage_)
* **Peak TTL:** Time To Live of decay peak before it falls back (in milliseconds)
* **Peak falloff:** Decay rate of decay peak after TTL (in dB/sec)

### Speed

Speedup or slowdown the media, without affecting the pitch.

### Pitch

Allow to change the media pitch by semitones.

### Compressor/Expander

Provide <a href="https://en.wikipedia.org/wiki/Dynamic_range_compression" target="_blank">Dynamic range compression</a>.

* **Type**
   * *Compressor*
   * *Expander*
* **Curve shape:** Selects how the ratio should be applied
   * *Hard Knee*
   * *Soft Knee*
* **Ratio:** Ratio that should be applied
* **Threshold:** minimum value from which the filter is activated (in dB)

### Audio Pan

Allow to control stereo panorama (left ⟷ right).

```{note}
When used the audio will be forced to stereo
```

### Video Alpha

Controls the opacity of the video stream for fade-to-black effects. Available in video and
image cue pipelines.

* **Alpha:** opacity level (0.0 = fully transparent/black, 1.0 = fully opaque)

When both `Volume` and `VideoAlpha` are present in a pipeline, fade operations run on both
simultaneously — audio fades to silence while video fades to black.

### Custom Element

Allow to manually create a custom GStreamer "elements" using the framework syntax,
some instruction and example can be found [here](media_custom_elements.md).

## Outputs

Send the audio (and/or video) to an output device

### Auto

Use the system-default audio output device, no option is provided.

### Video Sink

Combined audio and video output. Routes audio to the system audio device and video to the
projection window. Used automatically for video and image cues.

The video sink renders into the shared projection window (see [Video Output Window](#video-output-window)
above). A `tee` element splits the video stream to both the projection window and the optional
video monitor window.

### ALSA

Output to an ALSA device

* **ALSA device:** the output device to be used

### PulseAudio

Output to the default pulseaudio output device, no option is provided.

### Jack

Output to a <a href="http://www.jackaudio.org/" target="_blank">Jack</a> server.

```{warning}
Native JACK is not support in flatpaks, you can get JACK working via PipeWire (pipewire-jack)
```

The **Edit connections** button allow to view and change the connection for the cue:

```{image} ../_static/media_cue_jack_connections.png
:alt: Edit connection
```

On the left the cue outputs, on the right the available inputs, 
by selecting one input and one output it's possible to connect/disconnect using the provided buttons.

```{note}
Each cue will create a new connection on demand, do not rely on the given names.
```

