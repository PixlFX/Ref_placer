bl_info = {
    "name": "Ref_placer",
    "author": "p1xfx",
    "version": (0, 0, 1),
    "blender": (3, 0, 0),
    "category": "Lighting",
    "location": "View3D > View",
    "description": "Размещает объекты в отражении, указывая мышью",
    "warning": "",
    "tracker_url": ""
}

import bpy
import bpy.utils.previews
from bpy_extras import view3d_utils

import math
from mathutils import Vector
import os


AIM_AXIS = "Z"
USE_LOCATION = True
USE_ROTATION = True
DISTANCE = 0.0
SPEED_SLOW = 0.1
SPEED_FAST = 10.0


AXIS_ITEMS = (("-X", "X", ""),
              ("X", "-X", ""),
              ("-Y", "Y", ""),
              ("Y", "-Y", ""),
              ("-Z", "Z", ""),
              ("Z", "-Z", ""))


class OBJECT_OT_RefPlacer(bpy.types.Operator):
    """Класс оператора объекта."""
    bl_idname = "view3d.ref_placer"
    bl_label = "Ref_place"
    bl_description = "Перетащите по поверхности для размещения отражения выбранного объекта"
    bl_options = {'REGISTER', 'UNDO'}

    axis_value: bpy.props.EnumProperty(
        name="Ось",
        description="Ось, которая ориентирована к поверхности",
        items=AXIS_ITEMS,
        default=AIM_AXIS
    )
    location_value: bpy.props.BoolProperty(
        name="Положение",
        description="Влияет на положение выбранного объекта",
        default=USE_LOCATION
    )
    rotation_value: bpy.props.BoolProperty(
        name="Вращение",
        description="Влияет на вращение выбранного объекта",
        default=USE_ROTATION
    )
    distance_value: bpy.props.FloatProperty(
        name="Расстояние",
        description="Расстояние выбранного объекта до "
                    "поверхности. Установите 0, чтобы использовать текущее "
                    "расстояние объекта",
        default=DISTANCE
    )

    startPos = None
    startRot = None
    isDragging = False
    dragPos = None
    reflVector = None
    dist = 1.0
    shiftPressed = False
    ctrlPressed = False

    isModal = False

    def execute(self, context):
        """Выполнение оператора.

        Этот метод обязателен для отображения панели повтора.

        :param context: Текущий контекст.
        :type context: bpy.context
        """
        self.applyPlacement(context.object)
        self.isModal = False
        return {'FINISHED'}

    def modal(self, context, event):
        """Функция модального оператора.

        :param context: Текущий контекст.
        :type context: bpy.context
        :param event: Текущее событие.
        :type event: bpy.types.Event
        """

        if event.type == 'LEFTMOUSE':
            if not self.isDragging:
                self.isDragging = True
            else:
                self.isDragging = False
        if 'SHIFT' in event.type:
            if not self.shiftPressed:
                self.shiftPressed = True
            else:
                self.shiftPressed = False
        if 'CTRL' in event.type:
            if not self.ctrlPressed:
                self.ctrlPressed = True
            else:
                self.ctrlPressed = False

        if event.type in ['WHEELUPMOUSE', 'WHEELDOWNMOUSE']:
            self.set_distance_factor(event.type)
            self.set_position(context.object)

        if event.type == 'MOUSEMOVE' and self.isDragging:
            self.drag_placement(context, event)

        elif event.type in {'RET', 'NUMPAD_ENTER'}:
            self.reset(context)
            return {'FINISHED'}

        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            return self.cancel(context)

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        """Вызов оператора.

        :param context: Текущий контекст.
        :type context: bpy.context
        :param event: Текущее событие.
        :type event: bpy.types.Event
        """
        self.isModal = True

        if context.object:
            context.window_manager.modal_handler_add(self)
            context.workspace.status_text_set("LMB-Drag: Разместить, "
                                              "Esc/RMB: Отменить, "
                                              "Колесо мыши: Расстояние, "
                                              "Ctrl + Колесо мыши: Быстро, "
                                              "Shift + Колесо мыши: Медленно")

            self.startPos = context.object.location.copy()
            self.startRot = context.object.rotation_euler.copy()

            return {'RUNNING_MODAL'}

        self.report({'WARNING'}, "Не выбран объект для размещения")
        return self.cancel(context)

    def cancel(self, context):
        """Сброс и отмена текущей операции.

        :param context: Текущий контекст.
        :type context: bpy.context

        :return: Enum для отмены оператора.
        :rtype: enum
        """
        self.isModal = False

        if context.object:
            context.object.location = self.startPos
            context.object.rotation_euler = self.startRot

        self.reset(context)

        return {'CANCELLED'}

    def reset(self, context):
        """Сброс оператора.

        :param context: Текущий контекст.
        :type context: bpy.context
        """
        self.isModal = False
        self.isDragging = False
        context.workspace.status_text_set(None)

    def drag_placement(self, context, event):
        """Выполнение размещения объекта в зависимости от текущего
        положения курсора.

        :param context: Текущий контекст.
        :type context: bpy.context
        :param event: Текущее событие.
        :type event: bpy.types.Event

        :return: True, если объект найден и размещение может быть
                 выполнено.
        :rtype: bool
        """
        region = context.region
        regionView3d = context.region_data
        viewPos = event.mouse_region_x, event.mouse_region_y

        viewVector = view3d_utils.region_2d_to_vector_3d(region, regionView3d, viewPos)
        viewOrigin = view3d_utils.region_2d_to_origin_3d(region, regionView3d, viewPos)

        result, pos, normal, index, obj, mat = context.scene.ray_cast(context.view_layer.depsgraph,
                                                                      viewOrigin,
                                                                      viewVector)

        if not result or obj == context.object:
            return False

        self.dragPos = pos

        self.reflVector = reflection_vector(viewVector, normal)

        cursorPos = context.scene.cursor.location
        objPos = context.object.location
        if objPos == Vector((0.0, 0.0, 0.0)) or objPos == cursorPos:
            self.dist = distance(viewOrigin, self.dragPos)
        else:
            self.dist = distance(self.dragPos, context.object.location)

        self.applyPlacement(context.object)

    def set_distance_factor(self, eventType):
        """Настройка скорости установки расстояния в зависимости от
        нажатых клавиш-модификаторов.

        :param eventType: Текущая строка события.
        :type eventType: str
        """
        factor = 1.0
        speed = 0.05
        if self.shiftPressed:
            speed *= SPEED_SLOW
        elif self.ctrlPressed:
            speed *= SPEED_FAST

        if eventType == 'WHEELUPMOUSE':
            factor += speed
        elif eventType == 'WHEELDOWNMOUSE':
            factor -= speed

        if factor < 0:
            factor = 0

        self.dist *= factor

    def applyPlacement(self, obj):
        """Применение положения и вращения, основанного на глобальных
        настройках.

        :param obj: Объект.
        :type obj; bpy.types.Object
        """
        if self.location_value:
            self.set_position(obj)
        if self.rotation_value:
            self.set_rotation(obj)
        self.distance_value = self.dist

    def set_position(self, obj):
        """Установка результирующего положения выбранного объекта
        на основе текущих данных о перетаскивании.

        :param obj: Объект для размещения.
        :type obj; bpy.types.Object
        """
        if self.reflVector is None:
            return

        if not self.isModal:
            self.dist = self.distance_value
        obj.location = self.reflVector * self.dist + self.dragPos

    def set_rotation(self, obj):
        """Установка результирующей ориентации выбранного объекта
        на основе текущих данных о перетаскивании.

        :param obj: Объект для вращения.
        :type obj; bpy.types.Object
        """
        if self.reflVector is None:
            return

        upAxis = "Z"
        if self.axis_value in ["Z", "-Z"]:
            upAxis = "Y"
        quat = self.reflVector.to_track_quat(self.axis_value, upAxis)

        order = obj.rotation_mode

        if order == 'AXIS_ANGLE':
            obj.rotation_mode = 'QUATERNION'

        if order == 'QUATERNION':
            obj.rotation_quaternion = quat
        else:
            obj.rotation_euler = quat.to_euler(order)


def reflection_vector(viewVector, faceNormal):
    """Возвращает вектор отражения на основе данного вектора вида и
    нормали в точке отражения.

    :param viewVector: Вектор источника луча отражения.
    :type viewVector: вектор
    :param faceNormal: Вектор нормали в точке отражения.
    :type faceNormal: вектор

    :return: Вектор отражения.
    :rtype: вектор
    """
    doublePerp = 2.0 * viewVector @ faceNormal
    return viewVector - (doublePerp * faceNormal)


def distance(point1, point2):
    """Возвращает расстояние между двумя данными точками.

    :param point1: Первая точка.
    :type point1: вектор
    :param point2: Вторая точка.
    :type point2: вектор

    :return: Расстояние между точками.
    :rtype: float
    """
    value = 0.0
    for i in range(3):
        value += math.pow(point1[i] - point2[i], 2)
    return math.sqrt(value)


def menu_item(self, context):
    pcoll = preview_collections["icons"]
    icon = pcoll["tool_icon"]

    self.layout.separator()
    self.layout.operator(OBJECT_OT_RefPlacer.bl_idname,
                         text="Ref_placer",
                         icon_value=icon.icon_id)


preview_collections = {}

classes = [OBJECT_OT_RefPlacer]


def register():
    pcoll = bpy.utils.previews.new()
    icons_dir = os.path.join(os.path.dirname(__file__), "icons")
    pcoll.load("tool_icon", os.path.join(icons_dir, "Ref_placer.png"), 'IMAGE', True)
    preview_collections["icons"] = pcoll

    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_view.append(menu_item)

def unregister():
    for pcoll in preview_collections.values():
        bpy.utils.previews.remove(pcoll)
    preview_collections.clear()

    for cls in classes:
        bpy.utils.unregister_class(cls)
    bpy.types.VIEW3D_MT_view.remove(menu_item)


if __name__ == "__main__":
    register()
