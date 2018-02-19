from PyQt5.QtCore import QTimer, QPoint, QPointF, Qt
from PyQt5 import QtWidgets
import math
from PyQt5.QtGui import QSurfaceFormat
from .marc_paint_shapes import *
from .image_processing import *
import time

CornerTypes = enum(NONE="none", ROUNDED="rounded", FLAT_BRUSH="flat brush")
ResizeModes = enum(STRETCH="stretch", ANCHOR_MIDDLE="anchor middle", ANCHOR_CORNER="anchor corner")
Keys = enum(UP=Qt.Key_Up, DOWN=Qt.Key_Down, LEFT=Qt.Key_Left, RIGHT=Qt.Key_Right,
            BACKSPACE=Qt.Key_Backspace, RETURN=Qt.Key_Return, SHIFT=Qt.Key_Shift)
_shift_to_reg_key_code = {
    # for some reason, shift-1 (the exclamation point) has a different key code than 1, but we want to
    # always refer to the same spot on the keyboard
    33: 49, 64: 50, 35: 51, 36: 52, 37: 53, 94: 54, 38: 55, 42: 56, 40: 57, 41: 48, 95: 45, 43: 61,
    126: 96, 123: 91, 124: 92, 125: 93, 58: 59, 34: 39, 60: 44, 62: 46, 63: 47
}

class MarcPaintWidget(QtWidgets.QOpenGLWidget):

    VERTICES_PER_SEMICIRCLE = 6
    DOUBLE_CLICK_TIME = 0.3

    def __init__(self, parent=None, title="A Marc Paint Widget", view_bounds=(0, 1, 0, 1), window_size=(500, 500),
                 bg_color=(0.0, 0.0, 0.0, 1.0), textures=None):
        super().__init__(parent)
        this_format = QSurfaceFormat()
        this_format.setSamples(16)
        self.setFormat(this_format)

        # note: textures takes the form {name: path to image}
        if textures is None:
            textures = {}
        self.textures = {}
        self.textures_to_load = textures

        self.setWindowTitle(title)
        self.view_bounds = view_bounds
        self.setGeometry((get_screen_width() - window_size[0])/2,
                         (get_screen_height() - window_size[1])/2,
                         window_size[0], window_size[1])
        self.bg_color = bg_color
        self.setAutoFillBackground(False)
        self.last_resize = None
        self.resize_mode = ResizeModes.ANCHOR_MIDDLE
        self.squash_factor = float(self.get_view_width()) * self.height() / self.width() / self.get_view_height()

        # track mouse movements
        self.setMouseTracking(True)
        # this stores the current mouse view location
        self._mouse_view_location = (0, 0)
        self.click_started = False
        self.click_buttons = None
        self.click_count = 1
        self.last_click = -1
        # be sensitive to the pinch gesture
        self.grabGesture(4)
        # key event stuff
        self._keys_down = []
        self.use_shift_sensitive_key_codes = False

        # animation timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._do_animate_frame)
        QTimer().singleShot(0, self.on_load)
        self.last_animate = None
        self.animation_layers = []

        # shapes to be drawn
        self._shapes = []

    # ------------------------------ View and Window Stuff -----------------------------

    def set_view_bounds(self, x_min, x_max, y_min, y_max):
        self.view_bounds = (x_min, x_max, y_min, y_max)
        self.squash_factor = float(self.get_view_width()) * self.height() / self.width() / self.get_view_height()
        self.setup_2d_view()

    def center_view_at(self, x, y):
        # without resizing
        w, h = self.get_view_width(), self.get_view_height()
        self.set_view_bounds(x-w/2, x+w/2, y-h/2, y+h/2)

    def get_view_width(self):
        return self.view_bounds[1] - self.view_bounds[0]

    def get_view_height(self):
        return self.view_bounds[3] - self.view_bounds[2]

    def get_view_diagonal(self):
        return math.hypot(self.get_view_width(), self.get_view_height())

    def set_window_size(self, width, height):
        self.setGeometry((get_screen_width() - width)/2,
                         (get_screen_height() - height)/2,
                         width, height)
        self.squash_factor = float(self.get_view_width()) * height / width / self.get_view_height()

    def window_to_view(self, point):
        if isinstance(point, QPoint) or isinstance(point, QPointF):
            x, y = point.x(), point.y()
        else:
            x, y = point
        return (x / self.geometry().width()) * self.get_view_width() + self.view_bounds[0], \
               (1 - y / self.geometry().height()) * self.get_view_height() + self.view_bounds[2]

    def view_to_window(self, point):
        if isinstance(point, QPoint) or isinstance(point, QPointF):
            x, y = point.x(), point.y()
        else:
            x, y = point
        return ((x-self.view_bounds[0]) / self.get_view_width()) * self.geometry().width(), \
               (1 - (y - self.view_bounds[2]) / self.get_view_height()) * self.geometry().height()

    def set_resize_mode(self, resize_mode):
        self.resize_mode = resize_mode

    def set_bg_color(self, *color):
        self.bg_color = color

    def setup_2d_view(self):
        if self.context() is None:
            # If this is called before the GL Context is created, a godawful error will occur. This prevents that.
            return
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        glOrtho(self.view_bounds[0], self.view_bounds[1], self.view_bounds[2], self.view_bounds[3], -1.0, 1.0)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

    def paintGL(self):
        self._load_queued_textures()
        glClear(GL_COLOR_BUFFER_BIT)
        self.setup_2d_view()
        self.do_pre_painting()
        for shape in self._shapes:
            assert isinstance(shape, MarcShape)
            shape.paint()
        self.do_extra_painting()

    def do_pre_painting(self):
        # for any opengl called to be done before the flat drawing
        pass

    def do_extra_painting(self):
        # for any extra opengl called to be done after the flat drawing
        pass

    def resizeGL(self, w, h):
        self._load_queued_textures()
        if self.resize_mode is not ResizeModes.STRETCH:
            if self.last_resize is None:
                self.last_resize = (w, h)
            else:
                delta_width = self.get_view_width() * (float(w)/self.last_resize[0] - 1)
                delta_height = self.get_view_height() * (float(h)/self.last_resize[1] - 1)
                if self.resize_mode is ResizeModes.ANCHOR_MIDDLE:
                    self.view_bounds = (self.view_bounds[0] - delta_width/2,
                                        self.view_bounds[1] + delta_width/2,
                                        self.view_bounds[2] - delta_height/2,
                                        self.view_bounds[3] + delta_height/2)
                else:
                    self.view_bounds = (self.view_bounds[0],
                                        self.view_bounds[1] + delta_width,
                                        self.view_bounds[2] - delta_height,
                                        self.view_bounds[3])
                self.last_resize = (w, h)

        self.setup_2d_view()
        self.squash_factor = float(self.get_view_width()) * self.height() / self.width() / self.get_view_height()

    def initializeGL(self):
        # Called when the GL Context is created
        self._load_queued_textures()
        self.setup_2d_view()
        if len(self.bg_color) == 3:
            glClearColor(*(self.bg_color + (1.0, )))
        else:
            glClearColor(*self.bg_color)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glEnable(GL_MULTISAMPLE)

    def load_texture(self, texture_name, texture_path):
        # we can't just load textures at any time; it needs to be during the paintGL or initializeGL methods
        # so this method schedules it to be loaded
        self.textures_to_load[texture_name] = texture_path

    def _load_queued_textures(self):
        # this actually does the loading of the texture, called during paintGL or initializeGL
        for texture_name in list(self.textures_to_load.keys()):
            self.textures[texture_name] = MarcPyImage(self.textures_to_load.pop(texture_name))

    def get_texture_handler(self, texture_name):
        # This method exists because of animated images. Animated images are complicated, because we may be wanting to
        # draw several of them at different stages in their animation. So in this case we need a handler for each
        # drawing instance. This returns that handler, which we can pass to the texture param of drawing methods
        if texture_name not in self.textures:
            # return false if the texture doesn't exist or hasn't been processed yet
            return False
        marcpy_image = self.textures[texture_name]
        assert isinstance(marcpy_image, MarcPyImage)
        if marcpy_image.is_animated:
            return MarcpyAnimatedImageHandler(marcpy_image)
        else:
            return marcpy_image

    # ---------------------------- User Interaction Backend -----------------------------

    def mousePressEvent(self, event):
        buttons_and_modifiers = []
        if event.buttons() == Qt.LeftButton:
            buttons_and_modifiers.append("left")
        if event.buttons() == Qt.RightButton:
            buttons_and_modifiers.append("right")
        if event.modifiers() & Qt.ShiftModifier:
            buttons_and_modifiers.append("shift")
        if event.modifiers() & Qt.MetaModifier:
            buttons_and_modifiers.append("control")
        if event.modifiers() & Qt.AltModifier:
            buttons_and_modifiers.append("alt")
        if event.modifiers() & Qt.ControlModifier:
            buttons_and_modifiers.append("meta")
        self.click_started = True
        self.click_buttons = buttons_and_modifiers
        self.on_mouse_down(self._mouse_event_to_view_location(event), buttons_and_modifiers)
        super(MarcPaintWidget, self).mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        buttons_and_modifiers = []
        if event.buttons() == Qt.LeftButton:
            buttons_and_modifiers.append("left")
        if event.buttons() == Qt.RightButton:
            buttons_and_modifiers.append("right")
        if event.modifiers() & Qt.ShiftModifier:
            buttons_and_modifiers.append("shift")
        if event.modifiers() & Qt.MetaModifier:
            buttons_and_modifiers.append("control")
        if event.modifiers() & Qt.AltModifier:
            buttons_and_modifiers.append("alt")
        if event.modifiers() & Qt.ControlModifier:
            buttons_and_modifiers.append("meta")
        self.on_mouse_up(self._mouse_event_to_view_location(event), buttons_and_modifiers)
        if self.click_started:
            self.click_started = False
            if time.time() - self.last_click < MarcPaintWidget.DOUBLE_CLICK_TIME:
                self.click_count += 1
            else:
                self.click_count = 1
            self.last_click = time.time()
            self.on_mouse_click(self._mouse_event_to_view_location(event), self.click_buttons, self.click_count)
            self.click_buttons = None
        super(MarcPaintWidget, self).mousePressEvent(event)

    def wheelEvent(self, event):
        self.on_mouse_scroll(event.angleDelta().x(), event.angleDelta().y())

    def mouseMoveEvent(self, event):
        self.click_started = False
        self.click_buttons = None
        self._mouse_view_location = self._mouse_event_to_view_location(event)
        if event.buttons() == Qt.NoButton:
            self.on_mouse_move(self._mouse_view_location)
        else:
            buttons_and_modifiers = []
            if event.buttons() == Qt.LeftButton:
                buttons_and_modifiers.append("left")
            if event.buttons() == Qt.RightButton:
                buttons_and_modifiers.append("right")
            if event.modifiers() & Qt.ShiftModifier:
                buttons_and_modifiers.append("shift")
            if event.modifiers() & Qt.MetaModifier:
                buttons_and_modifiers.append("control")
            if event.modifiers() & Qt.AltModifier:
                buttons_and_modifiers.append("alt")
            if event.modifiers() & Qt.ControlModifier:
                buttons_and_modifiers.append("meta")
            self.on_mouse_drag(self._mouse_view_location, buttons_and_modifiers)
        super(MarcPaintWidget, self).mouseMoveEvent(event)

    def _mouse_event_to_view_location(self, event):
        return self.view_bounds[0] + (self.view_bounds[1] - self.view_bounds[0]) * float(event.x())/self.width(), \
            self.view_bounds[2] + (self.view_bounds[3] - self.view_bounds[2]) * (1-float(event.y())/self.height())

    def mouse_view_location(self):
        return self._mouse_view_location

    def keyPressEvent(self, event):
        key = event.key()
        if not self.use_shift_sensitive_key_codes and key in _shift_to_reg_key_code:
            key = _shift_to_reg_key_code[key]
        modifiers = []
        if event.modifiers() & Qt.ShiftModifier:
            modifiers.append("shift")
        if event.modifiers() & Qt.MetaModifier:
            modifiers.append("control")
        if event.modifiers() & Qt.AltModifier:
            modifiers.append("alt")
        if event.modifiers() & Qt.ControlModifier:
            modifiers.append("meta")
        if key not in self._keys_down:
            self.on_key_press(key, modifiers)
            self._keys_down.append(key)

    def keyReleaseEvent(self, event):
        key = event.key()
        if not self.use_shift_sensitive_key_codes and key in _shift_to_reg_key_code:
            key = _shift_to_reg_key_code[key]
        modifiers = []
        if event.modifiers() & Qt.ShiftModifier:
            modifiers.append("shift")
        if event.modifiers() & Qt.MetaModifier:
            modifiers.append("control")
        if event.modifiers() & Qt.AltModifier:
            modifiers.append("alt")
        if event.modifiers() & Qt.ControlModifier:
            modifiers.append("meta")
        self.on_key_release(key, modifiers)
        if key in self._keys_down:
            self._keys_down.remove(key)

    def get_keys_down(self):
        return self._keys_down

    def event(self, q_event):
        # general event handler, being overridden to listen for pinch gestures
        if isinstance(q_event, QtWidgets.QGestureEvent):
            for gesture in q_event.gestures():
                if isinstance(gesture, QtWidgets.QPinchGesture):
                    self.on_pinch_gesture(gesture)
        return super(MarcPaintWidget, self).event(q_event)

    # ---------------------------------- Animation! -----------------------------------

    def start_animation(self, interval):
        # interval in seconds
        def _first_animate():
            self.last_animate = time.time()
            a = time.time()
            self._do_animate_frame()
            self.timer.start(int(interval*1000))
        QTimer().singleShot(0, _first_animate)

    def _do_animate_frame(self):
        now = time.time()
        self.animate(now - self.last_animate)
        continuing_animation_layers = []
        for animation_layer in self.animation_layers:
            if animation_layer(now - self.last_animate, now - animation_layer.start_time):
                continuing_animation_layers.append(animation_layer)
        self.animation_layers = continuing_animation_layers
        self.last_animate = now
        self.repaint()

    def stop_animation(self):
        self.timer.stop()

    def add_animation_layer(self, animation_function):
        """
        :param animation_function: should be a function with parameters (dt, time_elapsed) representing the time since
        the last draw and the time since the start of the animation, respectively. Should return true if it wants to
        continue or False if it's time to end the animation.
        """
        animation_function.start_time = time.time()
        self.animation_layers.append(animation_function)

    # ---------------------------------- Paint Calls! -----------------------------------

    def clear(self):
        self._shapes = []

    def draw_points(self, vertices, colors, width=None):
        if not isinstance(vertices, np.ndarray):
            vertices = np.array(vertices)
        if not isinstance(colors, np.ndarray):
            colors = np.array(colors)

        if vertices.ndim == 1:
            vertices = np.array((vertices, ))

        if width is not None:
            deviations = np.tile(np.array([[-width/2, -width/2],
                                   [-width/2, width/2],
                                   [width/2, -width/2],
                                   [width/2, width/2],
                                   [-width/2, width/2],
                                   [width/2, -width/2]]), (vertices.shape[0], 1))
            triangle_vertices = vertices.repeat(6, axis=0) + deviations
            if colors.ndim == 1:
                self.fill_triangles(triangle_vertices, colors)
            else:
                self.fill_triangles(triangle_vertices, colors.repeat(6, axis=0))
        else:
            self._shapes.append(Points(self, vertices, colors))

    def fill_triangles(self, vertices, colors=None, texture=None, tex_coords=None, tex_color_blend_mode=GL_MODULATE):
        # takes a 2D array or list of vertices, and one of colors
        # either give a 1D array of RGB(A) values for color (all triangles painted that color)
        # or give a 2D array with one RGB(A) array for each vertex, or for each triangle

        if not isinstance(vertices, np.ndarray):
            vertices = np.array(vertices)
        if vertices.ndim == 1:
            vertices = np.array((vertices, ))

        if colors is not None:
            if not isinstance(colors, np.ndarray):
                colors = np.array(colors)

        if texture is not None:
            if isinstance(texture, str):
                if texture not in self.textures:
                    texture = None
                else:
                    texture = self.textures[texture]
            if not isinstance(tex_coords, np.ndarray):
                tex_coords = np.array(tex_coords)

        if texture is None and colors is None:
            colors = np.array((0, 0, 0))

        self._shapes.append(Triangles(self, vertices, colors=colors, texture=texture, tex_coords=tex_coords,
                                      tex_color_blend_mode=tex_color_blend_mode))

    def fill_triangle_fans(self, vertices, colors=None, starting_indices=None):
        # TODO: THIS IS INCOMPLETE: this method should really take a list of triangle fans and calculate the starting_indices from that
        # TODO: ALSO: TEXTURES
        if not isinstance(vertices, np.ndarray):
            vertices = np.array(vertices)
        if vertices.ndim == 1:
            vertices = np.array((vertices,))

        if colors is not None:
            if not isinstance(colors, np.ndarray):
                colors = np.array(colors)

        if colors is None:
            colors = np.array((0, 0, 0))

        self._shapes.append(TriangleFans(self, vertices, colors=colors, starting_indices=starting_indices))

    def fill_triangle_strips(self, vertices, colors=None, starting_indices=None):
        if not isinstance(vertices, np.ndarray):
            vertices = np.array(vertices)
        if vertices.ndim == 1:
            vertices = np.array((vertices,))

        if colors is not None:
            if not isinstance(colors, np.ndarray):
                colors = np.array(colors)

        if colors is None:
            colors = np.array((0, 0, 0))

        self._shapes.append(TriangleStrip(self, vertices, colors=colors, starting_indices=starting_indices))

    def fill_quads(self, vertices, colors=None, texture=None, tex_coords=None, tex_color_blend_mode=GL_MODULATE):
        if not isinstance(vertices, np.ndarray):
            vertices = np.array(vertices)

        if vertices.ndim == 1:
            vertices = np.array((vertices, ))

        first_corners = vertices[0::4]
        second_corners = vertices[1::4]
        third_corners = vertices[2::4]
        fourth_corners = vertices[3::4]
        triangle_vertices = np.empty([vertices.shape[0]*3//2, vertices.shape[1]])
        triangle_vertices[0::3, :] = first_corners.repeat(2, 0)
        triangle_vertices[2::3, :] = third_corners.repeat(2, 0)
        triangle_vertices[1::6, :] = second_corners
        triangle_vertices[4::6, :] = fourth_corners

        if texture is None:
            if colors is None:
                colors = np.array((0, 0, 0))
            if not isinstance(colors, np.ndarray):
                colors = np.array(colors)

            if colors.ndim == 2 and len(colors) == len(vertices):
                # one color per vertex, so colors like the vertices
                first_corners = colors[0::4]
                second_corners = colors[1::4]
                third_corners = colors[2::4]
                fourth_corners = colors[3::4]
                triangle_color_vertices = np.empty([colors.shape[0]*3//2, colors.shape[1]])
                triangle_color_vertices[0::3, :] = first_corners.repeat(2, 0)
                triangle_color_vertices[2::3, :] = third_corners.repeat(2, 0)
                triangle_color_vertices[1::6, :] = second_corners
                triangle_color_vertices[4::6, :] = fourth_corners
                colors = triangle_color_vertices
            elif colors.ndim == 2 and len(colors)*4 == len(vertices):
                # one color per quad, so just repeat each color once since we're getting two triangles
                colors = colors.repeat(2, 0)
            elif colors.ndim == 1:
                # nothing to do here: just one color for the whole thing
                pass
            else:
                raise WrongNumberOfVerticesException

            self.fill_triangles(triangle_vertices, colors)
        else:
            if isinstance(texture, str):
                if texture not in self.textures:
                    texture = None
                else:
                    texture = self.textures[texture]
            if not isinstance(tex_coords, np.ndarray):
                tex_coords = np.array(tex_coords)

            first_corners = tex_coords[0::4]
            second_corners = tex_coords[1::4]
            third_corners = tex_coords[2::4]
            fourth_corners = tex_coords[3::4]
            triangle_tex_vertices = np.empty([tex_coords.shape[0]*3//2, tex_coords.shape[1]])
            triangle_tex_vertices[0::3, :] = first_corners.repeat(2, 0)
            triangle_tex_vertices[2::3, :] = third_corners.repeat(2, 0)
            triangle_tex_vertices[1::6, :] = second_corners
            triangle_tex_vertices[4::6, :] = fourth_corners
            self.fill_triangles(triangle_vertices, colors=colors, texture=texture, tex_coords=triangle_tex_vertices,
                                tex_color_blend_mode=tex_color_blend_mode)

    def draw_quads(self, vertices, colors=None, width=None, texture=None, tex_coords=None):
        if not isinstance(vertices, np.ndarray):
            vertices = np.array(vertices)

        if vertices.ndim == 1:
            vertices = np.array((vertices, ))

        first_corners = vertices[0::4]
        second_corners = vertices[1::4]
        third_corners = vertices[2::4]
        fourth_corners = vertices[3::4]
        line_vertices = np.empty([vertices.shape[0]*2, vertices.shape[1]])
        line_vertices[0::8, :] = line_vertices[7::8, :] = first_corners
        line_vertices[1::8, :] = line_vertices[2::8, :] = second_corners
        line_vertices[3::8, :] = line_vertices[4::8, :] = third_corners
        line_vertices[5::8, :] = line_vertices[6::8, :] = fourth_corners

        if texture is None:
            if colors is None:
                colors = np.array((0, 0, 0))
            if not isinstance(colors, np.ndarray):
                colors = np.array(colors)

            if colors.ndim == 2 and len(colors) == len(vertices):
                # one color per vertex, so colors like the vertices
                first_corners = colors[0::4]
                second_corners = colors[1::4]
                third_corners = colors[2::4]
                fourth_corners = colors[3::4]
                line_color_vertices = np.empty([vertices.shape[0]*2, colors.shape[1]])
                line_color_vertices[0::8, :] = line_color_vertices[7::8, :] = first_corners
                line_color_vertices[1::8, :] = line_color_vertices[2::8, :] = second_corners
                line_color_vertices[3::8, :] = line_color_vertices[4::8, :] = third_corners
                line_color_vertices[5::8, :] = line_color_vertices[6::8, :] = fourth_corners
                colors = line_color_vertices
            elif colors.ndim == 2 and len(colors)*4 == len(vertices):
                # one color per quad, so just repeat each color once since we're getting four lines
                colors = colors.repeat(4, 0)
            elif colors.ndim == 1:
                # nothing to do here: just one color for the whole thing
                pass
            else:
                raise WrongNumberOfVerticesException

            self.draw_lines(line_vertices, colors, width=width)
        else:
            if isinstance(texture, str):
                if texture not in self.textures:
                    texture = None
                else:
                    texture = self.textures[texture]
            if not isinstance(tex_coords, np.ndarray):
                tex_coords = np.array(tex_coords)

            first_corners = tex_coords[0::4]
            second_corners = tex_coords[1::4]
            third_corners = tex_coords[2::4]
            fourth_corners = tex_coords[3::4]
            line_tex_vertices = np.empty([tex_coords.shape[0]*2, tex_coords.shape[1]])
            line_tex_vertices[0::8, :] = line_tex_vertices[7::8, :] = first_corners
            line_tex_vertices[1::8, :] = line_tex_vertices[2::8, :] = second_corners
            line_tex_vertices[3::8, :] = line_tex_vertices[4::8, :] = third_corners
            line_tex_vertices[5::8, :] = line_tex_vertices[6::8, :] = fourth_corners

            self.draw_lines(line_vertices, texture=texture, tex_coords=line_tex_vertices)

    def draw_image(self, location, texture_name, width=None, height=None, center_anchored=False):
        if texture_name not in list(self.textures.keys()):
            return

        if width is None:
            if height is None:
                width = height = 1.0
            else:
                width = height * self.textures[texture_name].get_current_image().width() / \
                        self.textures[texture_name].get_current_image().height() * self.squash_factor
        else:
            if height is None:
                height = width * self.textures[texture_name].get_current_image().height() / \
                         self.textures[texture_name].get_current_image().width() / self.squash_factor

        if center_anchored:
            self.fill_quads(((location[0]-width/2, location[1]-height/2), (location[0]-width/2, location[1]+height/2),
                             (location[0]+width/2, location[1]+height/2), (location[0]+width/2, location[1]-height/2)),
                            colors=(1, 1, 1), texture=texture_name, tex_coords=((0, 0), (0, 1),  (1, 1),  (1, 0)))
        else:
            self.fill_quads(((location[0], location[1]), (location[0], location[1]+height),
                             (location[0]+width, location[1]+height), (location[0]+width, location[1])),
                            colors=(1, 1, 1), texture=texture_name, tex_coords=((0, 0), (0, 1),  (1, 1),  (1, 0)))
        # returns size, if useful
        return width, height

    def fill_rects(self, locations, dimensions, colors, center_anchored=False):
        if not isinstance(locations, np.ndarray):
            locations = np.array(locations)
        if not isinstance(dimensions, np.ndarray):
            dimensions = np.array(dimensions)
        if not isinstance(colors, np.ndarray):
            colors = np.array(colors)
        if locations.ndim == 1:
            locations = np.array((locations, ))
        if dimensions.ndim == 1:
            dimensions = np.array((dimensions, ))

        vertices = np.empty((locations.shape[0]*4, 2))
        if center_anchored:
            (vertices[0::4])[:, 0] = locations[:, 0] - dimensions[:, 0]/2
            (vertices[1::4])[:, 0] = locations[:, 0] - dimensions[:, 0]/2
            (vertices[2::4])[:, 0] = locations[:, 0] + dimensions[:, 0]/2
            (vertices[3::4])[:, 0] = locations[:, 0] + dimensions[:, 0]/2
            (vertices[0::4])[:, 1] = locations[:, 1] - dimensions[:, 1]/2
            (vertices[1::4])[:, 1] = locations[:, 1] + dimensions[:, 1]/2
            (vertices[2::4])[:, 1] = locations[:, 1] + dimensions[:, 1]/2
            (vertices[3::4])[:, 1] = locations[:, 1] - dimensions[:, 1]/2
            self.fill_quads(vertices, colors)
        else:
            (vertices[0::4])[:, 0] = locations[:, 0]
            (vertices[1::4])[:, 0] = locations[:, 0]
            (vertices[2::4])[:, 0] = locations[:, 0] + dimensions[:, 0]
            (vertices[3::4])[:, 0] = locations[:, 0] + dimensions[:, 0]
            (vertices[0::4])[:, 1] = locations[:, 1]
            (vertices[1::4])[:, 1] = locations[:, 1] + dimensions[:, 1]
            (vertices[2::4])[:, 1] = locations[:, 1] + dimensions[:, 1]
            (vertices[3::4])[:, 1] = locations[:, 1]
            self.fill_quads(vertices, colors)

    def draw_rects(self, locations, dimensions, colors, width=None, center_anchored=False):
        if not isinstance(locations, np.ndarray):
            locations = np.array(locations)
        if not isinstance(dimensions, np.ndarray):
            dimensions = np.array(dimensions)
        if not isinstance(colors, np.ndarray):
            colors = np.array(colors)
        if locations.ndim == 1:
            locations = np.array((locations, ))
        if dimensions.ndim == 1:
            dimensions = np.array((dimensions, ))

        vertices = np.empty((locations.shape[0]*4, 2))
        if center_anchored:
            (vertices[0::4])[:, 0] = locations[:, 0] - dimensions[:, 0]/2
            (vertices[1::4])[:, 0] = locations[:, 0] - dimensions[:, 0]/2
            (vertices[2::4])[:, 0] = locations[:, 0] + dimensions[:, 0]/2
            (vertices[3::4])[:, 0] = locations[:, 0] + dimensions[:, 0]/2
            (vertices[0::4])[:, 1] = locations[:, 1] - dimensions[:, 1]/2
            (vertices[1::4])[:, 1] = locations[:, 1] + dimensions[:, 1]/2
            (vertices[2::4])[:, 1] = locations[:, 1] + dimensions[:, 1]/2
            (vertices[3::4])[:, 1] = locations[:, 1] - dimensions[:, 1]/2
            self.draw_quads(vertices, colors, width=width)
        else:
            (vertices[0::4])[:, 0] = locations[:, 0]
            (vertices[1::4])[:, 0] = locations[:, 0]
            (vertices[2::4])[:, 0] = locations[:, 0] + dimensions[:, 0]
            (vertices[3::4])[:, 0] = locations[:, 0] + dimensions[:, 0]
            (vertices[0::4])[:, 1] = locations[:, 1]
            (vertices[1::4])[:, 1] = locations[:, 1] + dimensions[:, 1]
            (vertices[2::4])[:, 1] = locations[:, 1] + dimensions[:, 1]
            (vertices[3::4])[:, 1] = locations[:, 1]
            self.draw_quads(vertices, colors, width=width)

    def draw_lines(self, vertices, colors, width=None, corner_type=CornerTypes.NONE):
        if not isinstance(vertices, np.ndarray):
            vertices = np.array(vertices)
        if not isinstance(colors, np.ndarray):
            colors = np.array(colors)

        if vertices.ndim == 1:
            vertices = np.array((vertices, ))

        if width is not None:
            assert vertices.shape[0] % 2 == 0
            assert colors.shape == (3,) or \
                colors.shape == (4,) or \
                (colors.shape[0]*2 == vertices.shape[0] or colors.shape[0] == vertices.shape[0]) and \
                (colors.shape[1] == 3 or colors.shape[1] == 4)

            # if one color for each line, repeat the colors so as to have one for each vertex
            if colors.ndim == 2 and colors.shape[0]*2 == vertices.shape[0]:
                colors = colors.repeat(2, axis=0)

            differences = vertices[1:] - vertices[:-1]
            # checks which differences are zero
            # if between the start and end of a single line, remove that line, since it does nothing
            # if between the end of one and the start of the other, we have to make sure to draw a connection
            diff_zero = (differences == 0).all(axis=1)
            # reshape so that vertex pairs are grouped together
            vertices = vertices.reshape([vertices.shape[0]//2, 2, 2])
            # any even numbered diff_zero is a line that starts and ends at the same point, so we remove it
            vertices_to_keep = np.where(~diff_zero[0::2])
            vertices = vertices[vertices_to_keep]

            # if we're removing any vertices, we need to remove the corresponding colors
            if colors.ndim == 2:
                colors = colors.reshape([colors.shape[0]//2, 2, colors.shape[1]])
                colors = colors[vertices_to_keep]
                colors = colors.reshape([colors.shape[0]*2, colors.shape[2]])

            differences = (differences[0::2])[vertices_to_keep]
            unit_differences = differences / np.hypot(differences[:, 0], differences[:, 1])[:, None]
            unit_perps = np.column_stack((unit_differences[:, 1], -unit_differences[:, 0]))

            vertices = vertices.reshape([vertices.shape[0]*2, 2])
            quad_vertices = np.empty((vertices.shape[0]*2, vertices.shape[1]))
            quad_vertices[::4] = vertices[::2] + (unit_perps[:] * width/2)
            quad_vertices[1::4] = vertices[::2] - (unit_perps[:] * width/2)
            quad_vertices[2::4] = vertices[1::2] - (unit_perps[:] * width/2)
            quad_vertices[3::4] = vertices[1::2] + (unit_perps[:] * width/2)

            # since we're drawing quads, we have to double the number of color vertices
            if colors.ndim == 2:
                quad_colors = colors.repeat(2, axis=0)
            else:
                quad_colors = colors
            if corner_type == CornerTypes.ROUNDED:
                self._shapes.append(DepthTestSwitch(self, True))
                self.fill_quads(quad_vertices, quad_colors)
                self.fill_arcs(vertices, np.full(vertices.shape[0], width/2), colors)
                self._shapes.append(DepthTestSwitch(self, False))
            else:
                self.fill_quads(quad_vertices, quad_colors)
        else:
            self._shapes.append(Lines(self, vertices, colors))

    def draw_polygons(self, vertices, colors, start_indices=None):
        if not isinstance(vertices, np.ndarray):
            vertices = np.array(vertices)
        if not isinstance(colors, np.ndarray):
            colors = np.array(colors)
        assert vertices.ndim == 2 and vertices.shape[1] == 2

        self._shapes.append(LineLoops(self, vertices, colors, start_indices))

    def draw_line_strip(self, vertices, colors, width=None, corner_type=CornerTypes.ROUNDED, double_back=True):
        if not isinstance(vertices, np.ndarray):
            vertices = np.array(vertices)
        if not isinstance(colors, np.ndarray):
            colors = np.array(colors)

        assert colors.shape == (3,) or \
            colors.shape == (4,) or \
            colors.shape[0] == vertices.shape[0] and \
            colors.shape[1] == 3 or colors.shape[1] == 4

        if width is not None:
            if corner_type == CornerTypes.FLAT_BRUSH:
                # find differences between vertices
                differences = vertices[1:] - vertices[:-1]
                # which are zero?
                diff_zero = (differences == 0).all(axis=1)
                # vertices that are the same as the previous are removed
                # need to add a False at the beginning, since the first vertex is obviously not the same as its predecessor
                vertices_to_keep = np.where(~np.roll(np.append(diff_zero, False), 1))
                vertices = vertices[vertices_to_keep]
                if vertices.shape[0] < 2:
                    # need at least two points to make a line strip
                    return
                differences = differences[~diff_zero]
                if colors.ndim == 2:
                    colors = colors[vertices_to_keep]

                unit_differences = differences / np.hypot(differences[:, 0], differences[:, 1])[:, None]
                unit_perps = np.column_stack((unit_differences[:, 1], -unit_differences[:, 0]))

                # if the direction vectors are farther than 90 degrees apart (equivalent to being more than root 2
                # apart in terms of distance), then there is an orientation change to account for
                direction_difference = unit_differences[:-1] - unit_differences[1:]
                more_than_90 = np.hypot(direction_difference[:, 0], direction_difference[:, 1]) > 1.41421356237

                average_directions = np.empty((vertices.shape[0] - 2, vertices.shape[1]))
                if double_back:
                    orientation_changes = np.where(more_than_90)
                    no_orientation_changes = np.where(~more_than_90)
                    average_directions[no_orientation_changes] = ((unit_differences[:-1])[no_orientation_changes] +
                                                               (unit_differences[1:])[no_orientation_changes]) / 2
                    average_directions[orientation_changes] = (-(unit_differences[:-1])[orientation_changes] +
                                                               (unit_differences[1:])[orientation_changes]) / 2
                else:
                    average_directions = (unit_differences[:-1] + unit_differences[1:]) / 2

                average_directions /= np.hypot(average_directions[:, 0], average_directions[:, 1])[:, None]
                average_perps = np.column_stack((average_directions[:, 1], -average_directions[:, 0]))

                perps_to_use = np.empty((vertices.shape[0], vertices.shape[1]))
                perps_to_use[0] = unit_perps[0]
                perps_to_use[1:-1] = average_perps
                perps_to_use[-1] = unit_perps[-1]

                # adjust width to compensate for sharper angles

                tri_strip_vertices = np.empty((vertices.shape[0]*2, vertices.shape[1]))
                tri_strip_vertices[0::2] = vertices - perps_to_use * width/2
                tri_strip_vertices[1::2] = vertices + perps_to_use * width/2

                # orientation changes flip the order of vertices until the next orientation change
                if double_back:
                    more_than_90 = np.concatenate((more_than_90, (False, )))
                    to_flip = np.where(np.cumsum(more_than_90) % 2)
                    temp = np.copy((tri_strip_vertices[2::2])[to_flip])
                    (tri_strip_vertices[2::2])[to_flip] = (tri_strip_vertices[3::2])[to_flip]
                    (tri_strip_vertices[3::2])[to_flip] = temp

                if colors.ndim == 2:
                    tri_strip_colors = np.repeat(colors, 2, axis=0)
                    self._shapes.append(TriangleStrip(self, tri_strip_vertices, tri_strip_colors))
                else:
                    self._shapes.append(TriangleStrip(self, tri_strip_vertices, colors))
            elif corner_type == CornerTypes.ROUNDED:
                new_vertices = np.empty(((vertices.shape[0]-1)*2, vertices.shape[1]))
                new_vertices[0::2] = vertices[:-1]
                new_vertices[1::2] = vertices[1:]
                if colors.ndim == 2:
                    new_colors = np.empty(((colors.shape[0]-1)*2, colors.shape[1]))
                    new_colors[0::2] = new_colors[:-1]
                    new_colors[1::2] = new_colors[1:]
                    self.draw_lines(new_vertices, new_colors, width=width, corner_type=corner_type)
                else:
                    self.draw_lines(new_vertices, colors, width=width, corner_type=corner_type)
        else:
            self._shapes.append(LineStrip(self, vertices, colors))

    def draw_text(self, text, mouse_location, size, color, font_name, styles="",
                  anchor_type=TextAnchorType.ANCHOR_BOTTOM_LEFT, include_descent_in_height=True):
        self._shapes.append(TextShape(self, text, mouse_location, size, font_name, color, styles=styles,
                                      anchor_type=anchor_type, include_descent_in_height=include_descent_in_height))

    def fill_arcs(self, centers, radii, colors, angle_ranges=(0, 2*math.pi), num_segments=100):
        # takes a numpy N x 2 numpy array of center locations
        # a N length or N x 2 array of radii ( N x 2 allows for ellipses )
        # a single color, an N x (3 or 4) array of colors for each arc separately,
        #  or a 2*N x (3 or 4) array of inner and outer colors for each arc
        # and either a single angle range (default 0 -> 2*pi draws full circles) or a separate
        # angle range for each arc.
        if not isinstance(centers, np.ndarray):
            centers = np.array(centers, dtype=float)
        if not isinstance(radii, np.ndarray):
            if hasattr(radii, "__len__"):
                radii = np.array(radii, dtype=float)
            else:
                # we were just given a single number for the radius of every arc
                radii = np.full((centers.shape[0],), radii, dtype=float)
        if not isinstance(colors, np.ndarray):
            colors = np.array(colors)
        if not isinstance(angle_ranges, np.ndarray):
            angle_ranges = np.array(angle_ranges)

        assert num_segments >= 2

        if centers.ndim == 1:
            assert centers.shape[0] == 2
            centers = np.array([centers])
        else:
            assert centers.ndim == 2 and centers.shape[1] == 2

        assert radii.shape[0] == centers.shape[0]
        assert angle_ranges.shape == (2,) or centers.shape[0] == angle_ranges.shape[0] and angle_ranges.shape[1] == 2
        # either one color for all arcs, one color per arc
        # or 2 colors for all arcs (center color, edge color)
        assert colors.shape == (3,) or \
            colors.shape == (4,) or \
            colors.ndim == 2 and (colors.shape[1] == 3 or colors.shape[1] == 4) and \
            (colors.shape[0] == centers.shape[0]*2 or
             colors.shape[0] == centers.shape[0])

        # start with all the edges at the centers of each arc
        edges = centers.repeat(num_segments + 1, axis=0)

        # then calculate the displacements from the centers for each edge point
        if angle_ranges.ndim == 1:
            angles = np.linspace(angle_ranges[0], angle_ranges[1], num_segments+1)
            displacements = np.tile(np.column_stack((np.cos(angles), np.sin(angles))), (centers.shape[0], 1))
        else:
            zero_to_one_ramps = np.tile(np.linspace(0, 1, num_segments+1), centers.shape[0])
            ranges_repeated = angle_ranges.repeat(num_segments+1, axis=0)
            angles = ranges_repeated[:, 0] * (1-zero_to_one_ramps) + ranges_repeated[:, 1] * zero_to_one_ramps
            displacements = np.column_stack((np.cos(angles), np.sin(angles)))

        if radii.ndim == 2:
            edges += radii.repeat(num_segments+1, axis=0)*displacements
        else:
            edges += radii.repeat(num_segments+1, axis=0)[:, np.newaxis]*displacements

        # finally, insert the centers
        insert_locations = np.arange(0, edges.shape[0], num_segments+1)

        vertices = np.insert(edges, insert_locations, centers, axis=0)
        if centers.shape[0] == 1:
            start_indices = None
        else:
            start_indices = np.arange(0, vertices.shape[0], num_segments+2)

        if colors.ndim == 2:
            if colors.shape[0] == centers.shape[0]:
                new_colors = colors.repeat(num_segments + 2, axis=0)
            elif colors.shape[0] == centers.shape[0]*2:
                # all but the starting center colors will be the edge colors
                new_colors = colors[1::2].repeat(num_segments + 2, axis=0)
                # the the first color of each circle, however, will be the center color
                new_colors[0::num_segments + 2] = colors[0::2]
            self._shapes.append(TriangleFans(self, vertices, new_colors, starting_indices=start_indices))
        else:
            self._shapes.append(TriangleFans(self, vertices, colors, starting_indices=start_indices))

    def fill_rings(self, centers, inner_radii, outer_radii, colors, angle_ranges=(0, 2*math.pi), num_segments=100):
        # takes a numpy N x 2 numpy array of center locations
        # a N length or N x 2 array of radii ( N x 2 allows for ellipses )
        # a single color, an N x (3 or 4) array of colors for each arc separately,
        #  or a 2*N x (3 or 4) array of inner and outer colors for each arc
        # and either a single angle range (default 0 -> 2*pi draws full circles) or a separate
        # angle range for each arc.
        if not isinstance(centers, np.ndarray):
            centers = np.array(centers)
        if not isinstance(inner_radii, np.ndarray):
            inner_radii = np.array(inner_radii)
        if not isinstance(outer_radii, np.ndarray):
            outer_radii = np.array(outer_radii)
        if not isinstance(colors, np.ndarray):
            colors = np.array(colors)
        if not isinstance(angle_ranges, np.ndarray):
            angle_ranges = np.array(angle_ranges)

        if centers.ndim == 1:
            assert centers.shape[0] == 2
            centers = np.array([centers])
        else:
            assert centers.ndim == 2 and centers.shape[1] == 2

        assert num_segments >= 2

        if outer_radii.shape[0] == 1:
            outer_radii = outer_radii.repeat(centers.shape[0])

        if inner_radii.shape[0] == 1:
            inner_radii = inner_radii.repeat(centers.shape[0])

        assert outer_radii.shape[0] == centers.shape[0]
        assert inner_radii.shape[0] == centers.shape[0]

        assert angle_ranges.shape == (2,) or centers.shape[0] == angle_ranges.shape[0] and angle_ranges.shape[1] == 2
        # either one color for all arcs, one color per arc
        # or 2 colors for all arcs (center color, edge color)
        assert colors.shape == (3,) or \
            colors.shape == (4,) or \
            colors.ndim == 2 and (colors.shape[1] == 3 or colors.shape[1] == 4) and \
            (colors.shape[0] == centers.shape[0]*2 or
             colors.shape[0] == centers.shape[0])

        # inner edges go |_|__|__|__|__|
        # outer edges go |__|__|__|__|_|
        # we alternate in-out-in-out
        # so six segments divides it into (6-1)*2+1 = 11 pieces
        num_piece_subdivisions = (num_segments-1)*2 + 1

        # start with all the edges at the centers of each arc
        vertices = centers.repeat((num_segments+1)*2, axis=0)

        # then calculate the displacements from the centers for each edge point
        if angle_ranges.ndim == 1:
            angles = np.linspace(angle_ranges[0], angle_ranges[1], num_piece_subdivisions+1)
            angles = np.insert(angles, [0, angles.shape[0]], [angles[0], angles[angles.shape[0]-1]], axis=0)
            displacements = np.tile(np.column_stack((np.cos(angles), np.sin(angles))), (centers.shape[0], 1))
        else:
            zero_to_one_ramps = np.tile(np.linspace(0, 1, num_piece_subdivisions+1), centers.shape[0])
            ranges_repeated = angle_ranges.repeat(num_piece_subdivisions+1, axis=0)
            angles = ranges_repeated[:, 0] * (1-zero_to_one_ramps) + ranges_repeated[:, 1] * zero_to_one_ramps
            # we need to repeat the start and end angles, since both inner and outer edges use both
            start_angles = np.arange(0, centers.shape[0])*(num_piece_subdivisions+1)
            end_angles = start_angles + num_piece_subdivisions
            to_repeat = np.concatenate([start_angles, end_angles])
            angles =  np.insert(angles, to_repeat, angles[to_repeat])
            displacements = np.column_stack((np.cos(angles), np.sin(angles)))

        if inner_radii.ndim == 2:
            vertices[0::2] += inner_radii.repeat(num_segments+1, axis=0)*displacements[0::2]
        else:
            vertices[0::2] += inner_radii.repeat(num_segments+1, axis=0)[:, np.newaxis]*displacements[0::2]

        if outer_radii.ndim == 2:
            vertices[1::2] += outer_radii.repeat(num_segments+1, axis=0)*displacements[1::2]
        else:
            vertices[1::2] += outer_radii.repeat(num_segments+1, axis=0)[:, np.newaxis]*displacements[1::2]

        if centers.shape[0] == 1:
            start_indices = None
        else:
            start_indices = np.arange(0, vertices.shape[0], (num_segments+1)*2)

        if colors.ndim == 2:
            if colors.shape[0] == centers.shape[0]:
                new_colors = colors.repeat((num_segments+1)*2, axis=0)
            elif colors.shape[0] == centers.shape[0]*2:
                inner_colors = colors[0::2]
                outer_colors = colors[1::2]
                inner_colors = inner_colors.repeat(num_segments+1, axis=0)
                outer_colors = outer_colors.repeat(num_segments+1, axis=0)
                new_colors = np.empty([vertices.shape[0], colors.shape[1]])
                new_colors[0::2] = inner_colors
                new_colors[1::2] = outer_colors

            self._shapes.append(TriangleStrip(self, vertices, new_colors, start_indices))
        else:
            self._shapes.append(TriangleStrip(self, vertices, colors, start_indices))

    # ------------------------ User interaction methods to implement ---------------------------

    def on_mouse_down(self, location, buttons_and_modifiers):
        pass

    def on_mouse_up(self, location, buttons_and_modifiers):
        pass

    def on_mouse_click(self, location, buttons_and_modifiers, click_count):
        pass

    def on_mouse_move(self, location):
        pass

    def on_mouse_drag(self, location, buttons):
        pass

    def on_mouse_scroll(self, delta_x, delta_y):
        pass

    def on_pinch_gesture(self, gesture):
        # gesture is an instance of QtWidgets.QPinchGesture
        pass

    def on_key_press(self, key, modifiers):
        pass

    def on_key_release(self, key, modifiers):
        pass

    # ----------------------------- Main draw methods to implement -----------------------------

    def on_load(self):
        pass

    def animate(self, dt):
        pass


def get_screen_width():
    return QtWidgets.QDesktopWidget().availableGeometry().width()


def get_screen_height():
    return QtWidgets.QDesktopWidget().availableGeometry().height()


class WrongNumberOfVerticesException(Exception):
    pass

