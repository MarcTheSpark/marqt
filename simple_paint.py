from .marc_paint import *
from PyQt5 import QtWidgets


def do_simple_paint(painting_function, window_dimensions=(500, 500), view_bounds=(0, 1, 0, 1), animate_dt=None,
                    bg_color=(1.0, 1.0, 1.0, 1.0), textures=None):
    """
    :param bg_color: duh
    :param textures: duh
    :param painting_function: function that takes paint_widget as first argument and dt as second if dt is not None
    :param window_dimensions: duh
    :param view_bounds: duh
    :param dt: If set to a value, calls painting_function regularly for animation, otherwise calls in on_load
    """
    app = QtWidgets.QApplication(["Simple Paint"])

    class SimplePaintWidget(MarcPaintWidget, object):
        def __init__(self):
            super(SimplePaintWidget, self).__init__(window_size=window_dimensions,
                                                    bg_color=bg_color, textures=textures, title="Simple Paint")
            self.set_view_bounds(*view_bounds)
            if animate_dt is not None:
                self.start_animation(animate_dt)

        def on_load(self):
            if animate_dt is None:
                try:
                    painting_function(self)
                except TypeError:
                    painting_function(self, 0)

        def animate(self, dt):
            try:
                painting_function(self, dt)
            except TypeError:
                painting_function(self)

    simple_paint_widget = SimplePaintWidget()
    simple_paint_widget.raise_()
    simple_paint_widget.show()
    app.exec_()


# DRAWING EXAMPLE:


# def simple_paint(paint_widget):
#     assert isinstance(paint_widget, MarcPaintWidget)
#     paint_widget.clear()
#     # paint_widget.fill_arcs((0.5, 0.5), (0.25,), (0, 0, 0))
#     paint_widget.draw_text("Hello There", (0.5, 0.5), 0.2, (0, 0, 0), "Times", anchor_type=TextAnchorType.ANCHOR_BOTTOM_LEFT)
#
# do_simple_paint(simple_paint)


# ANIMATION EXAMPLE:

# t = 0
#
#
# def simple_paint(paint_widget, dt):
#     global t
#     assert isinstance(paint_widget, MarcPaintWidget)
#     t += dt
#     paint_widget.clear()
#     paint_widget.fill_arcs((0.5+t/10, 0.5), (0.25,), (0, 0, 0))
#
# do_simple_paint(simple_paint, animate_dt=0.01)