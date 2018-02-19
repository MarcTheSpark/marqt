from abc import ABC, abstractmethod
from OpenGL.GL import *
import numpy as np
from PyQt5.QtGui import QFont, QFontMetricsF, QPainter, QColor
from PyQt5.QtCore import QRectF
from .image_processing import MarcPyImageHandler

from marcpy.utilities import enum


TextAnchorType = enum(ANCHOR_CENTER="anchor center", ANCHOR_CENTER_LEFT="anchor center left",
                      ANCHOR_CENTER_RIGHT="anchor center right", ANCHOR_CENTER_TOP="anchor center top",
                      ANCHOR_CENTER_BOTTOM="anchor center bottom", ANCHOR_CORNER="anchor bottom left",
                      # ANCHOR CORNER AND ANCHOR_RIGHT_CORNER ARE THE OLD NAMES I USED FOR BOTTOM LEFT AND TOP RIGHT
                      ANCHOR_BOTTOM_LEFT="anchor bottom left", ANCHOR_RIGHT_CORNER="anchor top right",
                      ANCHOR_TOP_RIGHT="anchor top right", ANCHOR_TOP_LEFT="anchor top left",
                      ANCHOR_BOTTOM_RIGHT="anchor bottom right")


class MarcShape(ABC):

    def __init__(self, host_widget):
        self.host_widget = host_widget

    @abstractmethod
    def paint(self):
        pass


class TextShape(MarcShape):
    def __init__(self, host_widget, text, location, size, font_name, color, styles="",
                 anchor_type=TextAnchorType.ANCHOR_BOTTOM_LEFT, include_descent_in_height=True):
        # size either refers to the point size (relative to the view height)
        # or to the max width and max height in view coordinates
        """

        :param host_widget: the MarcPaintWidget in which this is being drawn
        :param text: The text to be written
        :param size: The size of the text to be written in view coordinates. Either a number, in which case this will be
        the height of the text, or a tuple of (width, height) in which case the text will be made as big as possible
        such that it fits in the bounding box.
        :param font_name: Font family name
        :param color: duh
        :param styles: "bold", "italic", or "bold italic"
        :param anchor_type: one of the TextAnchorTypes. Either determines the position of the draw location within the
        text if we are given a height only in the size parameter, or determines the position of the text in the bounding
        box if we are given a (width, height) tuple in the size parameter. Note that the location parameter defines the
        lower left corner of the bounding box.
        :param include_descent_in_height: determines whether we include the descent in the height of the letters, both
        for size and for anchoring purposes.
        """
        super().__init__(host_widget)
        self.text = text
        self.font_name = font_name
        self.color = tuple(int(k*255) for k in color)
        self.size = (float(size[0]), float(size[1])) if hasattr(size, "__len__") else float(size)

        self.view_location = location

        self.anchor_type = anchor_type
        self.include_descent_in_height = include_descent_in_height

        # These two attributes need to be recalculated at every draw
        self.position = None
        self.font = None
        self.styles = styles.lower()

    def set_font_and_position(self):
        goal_view_font_height = self.size[1] if isinstance(self.size, tuple) else self.size
        goal_window_font_height = goal_view_font_height / self.host_widget.get_view_height() * self.host_widget.height()
        goal_view_font_width = self.size[0] if isinstance(self.size, tuple) else float("inf")
        goal_window_font_width = goal_view_font_width / self.host_widget.get_view_height() * self.host_widget.height()

        self.font = QFont(self.font_name, goal_window_font_height)

        if "italic" in self.styles:
            self.font.setItalic(True)
        if "bold" in self.styles:
            self.font.setBold(True)

        font_met = QFontMetricsF(self.font)
        bounding_rect = font_met.tightBoundingRect(self.text)
        effective_height = bounding_rect.height() if self.include_descent_in_height \
            else bounding_rect.height() - bounding_rect.bottom()
        resize_ratio = max(bounding_rect.width() / goal_window_font_width, effective_height / goal_window_font_height)
        self.font.setPointSizeF(self.font.pointSizeF() / resize_ratio)

        # at this point, we should have the font at the right size to fill the desired height or bounding box
        # recalculate its metrics
        font_met = QFontMetricsF(self.font)
        bounding_rect = font_met.tightBoundingRect(self.text)
        assert isinstance(bounding_rect,QRectF)
        self.position = self.host_widget.view_to_window(self.view_location)

        if self.include_descent_in_height:
            x_zeroing_adjustment, y_zeroing_adjustment = -bounding_rect.left(), -bounding_rect.bottom()
            effective_height = bounding_rect.height()
        else:
            x_zeroing_adjustment, y_zeroing_adjustment = -bounding_rect.left(), 0
            effective_height = bounding_rect.height() - bounding_rect.bottom()

        if self.anchor_type in (TextAnchorType.ANCHOR_CENTER_TOP, TextAnchorType.ANCHOR_TOP_LEFT,
                                TextAnchorType.ANCHOR_TOP_RIGHT):
            # top vertically
            if hasattr(self.size, "__len__"):
                y_anchoring_adjustment = effective_height - goal_window_font_height
            else:
                # point location
                y_anchoring_adjustment = effective_height
        elif self.anchor_type in (TextAnchorType.ANCHOR_CENTER, TextAnchorType.ANCHOR_CENTER_LEFT,
                                TextAnchorType.ANCHOR_CENTER_RIGHT):
            # centered vertically
            if hasattr(self.size, "__len__"):
                y_anchoring_adjustment = (effective_height - goal_window_font_height) / 2
            else:
                # point location
                y_anchoring_adjustment = effective_height / 2
        else:
            # (default) bottom vertically
            y_anchoring_adjustment = 0

        if self.anchor_type in (TextAnchorType.ANCHOR_TOP_RIGHT, TextAnchorType.ANCHOR_CENTER_RIGHT,
                                  TextAnchorType.ANCHOR_BOTTOM_RIGHT):
            # right horizontally
            if hasattr(self.size, "__len__"):
                x_anchoring_adjustment = -bounding_rect.width() + goal_window_font_width
            else:
                # point location
                x_anchoring_adjustment = -bounding_rect.width()
        elif self.anchor_type in (TextAnchorType.ANCHOR_CENTER_TOP, TextAnchorType.ANCHOR_CENTER,
                                  TextAnchorType.ANCHOR_CENTER_BOTTOM):
            # center horizontally
            if hasattr(self.size, "__len__"):
                x_anchoring_adjustment = (-bounding_rect.width() + goal_window_font_width) / 2
            else:
                # point location
                x_anchoring_adjustment = -bounding_rect.width() / 2
        else:
            # (default) left horizontally
            x_anchoring_adjustment = 0

        self.position = self.position[0] + x_zeroing_adjustment + x_anchoring_adjustment, \
                        self.position[1] + y_zeroing_adjustment + y_anchoring_adjustment

    def paint(self):
        self.set_font_and_position()
        painter = QPainter(self.host_widget)
        painter.setPen(QColor(*self.color))
        painter.setFont(self.font)
        painter.drawText(self.position[0], self.position[1], self.text)
        painter.end()
        # Resets the OpenGL states we need for drawing
        self.host_widget.initializeGL()


class MarcGLShape(MarcShape):

    def __init__(self, host_widget, draw_mode, vertices, colors=None, texture=None, tex_coords=None,
                 tex_color_blend_mode=GL_MODULATE, element_length=1, starting_indices=None):
        """
        :param vertices: a 2D numpy array of shape [N, 2], where N is a multiple of 3
        :param colors: a 2D numpy array of shape [N, 3] or [N, 4]
        :param texture: a MarcPyImageHandler
        :param tex_coords: The coordinates within the texture, normalized to 0-1 on each axis
        :param tex_color_blend_mode: how texture is blended with color. Generally GL_MODULATE, but could be different
        """

        super().__init__(host_widget)
        assert isinstance(vertices, np.ndarray)
        assert vertices.shape[0] % element_length == 0 and vertices.shape[1] == 2

        # if neither a texture not a color is defined, assume black
        if texture is None and colors is None:
            colors = np.array((0, 0, 0))

        # if we're using a texture, we should make sure that there are coordinates defined, and that there is the
        # same number of texture coordinates as vertex coordinates
        if texture is not None:
            assert tex_coords is not None and tex_coords.shape == vertices.shape

        # if we're setting the color, there are a number of possibilities
        if colors is not None:
            assert isinstance(colors, np.ndarray) and 1 <= colors.ndim <= 2

            if colors.ndim == 1:
                # just a single color for the whole thing
                assert colors.shape[0] == 3 or colors.shape[0] == 4
            else:
                # either one color per vertex or one color per shape. If the shapes are fixed length, like triangles,
                # then we check if colors.shape[0] * element_length == vertices.shape[0]. If variable, like in a
                # triangle fan using GLMultiDrawArrays, then we check that we have the same number of colors as
                # we have starting indices
                assert colors.shape[0] == vertices.shape[0] or colors.shape[0] * element_length == vertices.shape[0] or\
                       (starting_indices is not None and colors.shape[0] == starting_indices.shape[0])
                assert colors.shape[1] == 3 or colors.shape[1] == 4

                # one color per shape, with fixed shape length; we need to replicate the vertices
                if element_length > 1 and colors.shape[0]*element_length == vertices.shape[0]:
                    colors = np.column_stack([colors] * element_length).reshape(
                        [colors.shape[0] * element_length, colors.shape[1]]
                    )

                # one color per shape, with a variable shape length; we need to replicate the vertices
                if starting_indices is not None and colors.shape[0] == starting_indices.shape[0]:
                    repeats = np.diff(np.concatenate([starting_indices, [vertices.shape[0]]]))
                    colors = colors.repeat(repeats, axis=0)

        elif texture is not None:
            # this is important: if we're using a texture with no color info, we need to make sure the color is
            # changed to black or it might just have a weird color left over
            colors = np.array((0, 0, 0))

        if texture is not None:
            # texture is an image handler (either a MarcPyImage or a MarcpyAnimatedImageHandler)
            assert isinstance(texture, MarcPyImageHandler)
        self.texture = texture

        self.vertices = vertices
        self.colors = colors
        self.element_length = element_length
        self.draw_mode = draw_mode
        self.tex_coords = tex_coords
        self.tex_color_blend_mode = tex_color_blend_mode
        self.starting_indices = starting_indices
        self.counts = None if self.starting_indices is None \
            else np.diff(np.concatenate([starting_indices, [vertices.shape[0]]]))

    def paint(self):
        if self.colors.ndim == 1:
            if self.colors.shape == (4,):
                glColor4f(*self.colors)
            elif self.colors.shape == (3,):
                glColor3f(*self.colors)

        glEnableClientState(GL_VERTEX_ARRAY)

        if self.texture is not None:
            tex = self.texture.get_current_opengl_texture()
            glEnable(GL_TEXTURE_2D)
            glEnableClientState(GL_TEXTURE_COORD_ARRAY)
            glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, self.tex_color_blend_mode)

        glVertexPointer(2, GL_FLOAT, 0, self.vertices)

        if self.texture is not None:
            tex.bind()
            glTexCoordPointer(2, GL_FLOAT, 0, self.tex_coords)

        if self.colors is not None and self.colors.ndim > 1:
            glEnableClientState(GL_COLOR_ARRAY)
            glColorPointer(self.colors.shape[1], GL_FLOAT, 0, self.colors)

        if self.starting_indices is not None:
            glMultiDrawArrays(self.draw_mode, self.starting_indices, self.counts, len(self.starting_indices))
        else:
            glDrawArrays(self.draw_mode, 0, len(self.vertices))

        glFlush()
        glDisableClientState(GL_VERTEX_ARRAY)

        if self.colors is not None and self.colors.ndim > 1:
            glDisableClientState(GL_COLOR_ARRAY)
        if self.texture is not None:
            glDisableClientState(GL_TEXTURE_COORD_ARRAY)
            tex.release()


class Points(MarcGLShape):
    def __init__(self, host_widget, vertices, colors=None, texture=None, tex_coords=None,
                 tex_color_blend_mode=GL_MODULATE):
        super().__init__(host_widget, GL_POINTS, vertices, colors=colors, texture=texture, tex_coords=tex_coords,
                         tex_color_blend_mode=tex_color_blend_mode)


class Lines(MarcGLShape):
    def __init__(self, host_widget, vertices, colors=None, texture=None, tex_coords=None,
                 tex_color_blend_mode=GL_MODULATE, line_width=1):
        super().__init__(host_widget, GL_LINES, vertices, colors=colors, texture=texture, tex_coords=tex_coords,
                         tex_color_blend_mode=tex_color_blend_mode, element_length=2)
        self.line_width = line_width

    def paint(self):
        glLineWidth(self.line_width)
        super().paint()
        glLineWidth(1)


class LineStrip(MarcGLShape):
    def __init__(self, host_widget, vertices, colors=None, texture=None, tex_coords=None,
                 tex_color_blend_mode=GL_MODULATE, line_width=1):
        super().__init__(host_widget, GL_LINE_STRIP, vertices, colors=colors, texture=texture, tex_coords=tex_coords,
                         tex_color_blend_mode=tex_color_blend_mode)
        self.line_width = line_width

    def paint(self):
        glLineWidth(self.line_width)
        super().paint()
        glLineWidth(1)


class Triangles(MarcGLShape):

    def __init__(self, host_widget, vertices, colors=None, texture=None, tex_coords=None,
                 tex_color_blend_mode=GL_MODULATE):
        super().__init__(host_widget, GL_TRIANGLES, vertices, colors=colors, texture=texture, tex_coords=tex_coords,
                         tex_color_blend_mode=tex_color_blend_mode, element_length=3)


class LineLoops(MarcGLShape):

    def __init__(self, host_widget, vertices, colors=None, texture=None, tex_coords=None,
                 tex_color_blend_mode=GL_MODULATE, line_width=1, starting_indices=None):
        super().__init__(host_widget, GL_LINE_LOOP, vertices, colors=colors, texture=texture, tex_coords=tex_coords,
                         tex_color_blend_mode=tex_color_blend_mode, starting_indices=starting_indices)
        self.line_width = line_width

    def paint(self):
        glLineWidth(self.line_width)
        super().paint()
        glLineWidth(1)


class TriangleStrip(MarcGLShape):

    def __init__(self, host_widget, vertices, colors=None, texture=None, tex_coords=None,
                 tex_color_blend_mode=GL_MODULATE, starting_indices=None):
        super().__init__(host_widget, GL_TRIANGLE_STRIP, vertices, colors=colors, texture=texture, tex_coords=tex_coords,
                         tex_color_blend_mode=tex_color_blend_mode, starting_indices=starting_indices)


class TriangleFans(MarcGLShape):

    def __init__(self, host_widget, vertices, colors=None, texture=None, tex_coords=None,
                 tex_color_blend_mode=GL_MODULATE, starting_indices=None):
        super().__init__(host_widget, GL_TRIANGLE_FAN, vertices, colors=colors, texture=texture, tex_coords=tex_coords,
                         tex_color_blend_mode=tex_color_blend_mode, starting_indices=starting_indices)


class DepthTestSwitch(MarcShape):
    def __init__(self, host_widget, on_or_off, includes_alpha=True):
        super().__init__(host_widget)
        self.includes_alpha = includes_alpha
        self.on_or_off = on_or_off

    def paint(self):
        if self.on_or_off:
            glEnable(GL_DEPTH_TEST)
            glClear(GL_DEPTH_BUFFER_BIT)
        else:
            glDisable(GL_DEPTH_TEST)