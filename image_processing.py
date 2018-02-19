from abc import ABC, abstractmethod
from PyQt5.QtGui import QImage, QImageReader, QOpenGLTexture
import threading
import time
# The MarcPyImage class takes a path to an image and reads it into one or several QImages (in the case of
# an animated image). It also creates a QOpenGLTexture for each QImage.
# For an animated image, animation can take place on the MarcPyImage itself (which would animate each image
# simultaneously) or a MarcpyAnimatedImageHandler can be fashioned from a MarcPyImage so as to control
# individual instances of an animated image.


class MarcPyImageHandler(ABC):

    @abstractmethod
    def get_current_image(self):
        pass

    @abstractmethod
    def get_current_opengl_texture(self):
        pass


class MarcPyImage(MarcPyImageHandler):

    def __init__(self, file_path, make_opengl_textures=True):
        image_reader = QImageReader(file_path)
        self.is_animated = image_reader.supportsAnimation()
        if self.is_animated:
            self.num_frames = image_reader.imageCount()
            # -1 means loop infinitely, 0 means no loop, > 0 is finite # of loops
            self.loop_count = image_reader.loopCount()
            self.loops_remaining = 0
            self.frames = []
            self.delays = []
            while image_reader.currentImageNumber() < image_reader.imageCount() - 1:
                self.frames.append(image_reader.read())
                self.delays.append(image_reader.nextImageDelay())

            if make_opengl_textures:
                self.open_gl_textures = [QOpenGLTexture(this_frame.mirrored()) for this_frame in self.frames]
                self.made_opengl_textures = True

            self.frames_and_delays = zip(self.frames, self.delays)

            self.current_frame = 0
            self.animating = False
        else:
            self.image = image_reader.read()
            assert isinstance(self.image, QImage)
            if make_opengl_textures:
                self.open_gl_texture = QOpenGLTexture(self.image.mirrored())
                self.made_opengl_textures = True

    def start_animation(self):
        threading.Thread(target=self.animate).start()
        self.loops_remaining = self.loop_count

    def animate(self):
        while self.animating:
            if self.current_frame < self.num_frames - 1:
                # not the last frame
                self.current_frame += 1
            elif self.loops_remaining < 0:
                # last frame and we have infinite loops
                self.current_frame = 0
            elif self.loops_remaining > 0:
                # last frame and we have positive finite loops left
                self.current_frame = 0
                self.loops_remaining -= 1
            # Note that if loops_remaining is 0 then nothing happens; we just sit on the last frame

            time.sleep(self.delays[self.current_frame]/1000.)

    def stop_animation(self):
        self.animating = False

    def reset_animation(self):
        self.current_frame = 0

    def get_current_image(self):
        if not self.is_animated:
            # it's a single image
            return self.image
        else:
            # it's an animated image
            return self.frames[self.current_frame]

    def get_current_opengl_texture(self):
        if not self.made_opengl_textures:
            return None
        if not self.is_animated:
            # it's a single image
            return self.open_gl_texture
        else:
            # it's an animated image
            return self.open_gl_textures[self.current_frame]


class MarcpyAnimatedImageHandler(MarcPyImageHandler):

    def __init__(self, animated_marcpy_image):
        assert isinstance(animated_marcpy_image, MarcPyImage)
        assert animated_marcpy_image.is_animated
        self.animated_image = animated_marcpy_image
        self.loops_remaining = 0
        self.current_frame = 0
        self.animating = False

    def start_animation(self):
        anim_thread = threading.Thread(target=self.animate)
        anim_thread.daemon = True
        anim_thread.start()
        self.loops_remaining = self.animated_image.loop_count

    def animate(self):
        self.animating = True
        while self.animating:
            frame_start = time.time()
            if self.current_frame < self.animated_image.num_frames - 1:
                # not the last frame
                self.current_frame += 1
            elif self.loops_remaining < 0:
                # last frame and we have infinite loops
                self.current_frame = 0
            elif self.loops_remaining > 0:
                # last frame and we have positive finite loops left
                self.current_frame = 0
                self.loops_remaining -= 1
            # Note that if loops_remaining is 0 then nothing happens; we just sit on the last frame

            # for some reason, time.sleep often overshoots significantly, so we keep sleeping for 80% of the
            # desired interval until we've slept enough
            delay_time = self.animated_image.delays[self.current_frame] / 1000.
            while delay_time - (time.time() - frame_start) > 0:
                time.sleep(max(0, (delay_time - (time.time() - frame_start)) * 0.8))

    def stop_animation(self):
        self.animating = False

    def reset_animation(self):
        self.current_frame = 0

    def get_current_image(self):
        return self.animated_image.frames[self.current_frame]

    def get_current_opengl_texture(self):
        if not self.animated_image.made_opengl_textures:
            return None
        else:
            return self.animated_image.open_gl_textures[self.current_frame]