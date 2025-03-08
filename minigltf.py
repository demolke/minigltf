import bpy
from io import BytesIO
import numpy as np
import struct
import time

chunks = []

start = time.time()

output = BytesIO()

output.write(np.uint32(0x46546C67)) # magic == gLTF
output.write(np.uint32(2))          # version == 2
output.write(np.uint32(0x726e6769)) # length == garbage, godot doesn't care

json = BytesIO()
json.write(b'{')
json.write(b'"asset":{"version":"2.0","generator":"minigltf"},\n')

objs = [o for o in bpy.data.objects if o.type in ['MESH', 'ARMATURE']]
for a in bpy.data.armatures:
    objs += [b for b in a.bones]
meshes = []
armatures = []

# Nodes section
json.write(b'"nodes":[')
for i in range(len(objs)):
    o = objs[i]
    json.write(b'{"name":"')
    json.write(o.name.encode())
    json.write(b'"')

    if type(o) == bpy.types.Bone:
        translation = o.matrix_local.to_translation()
        quaternion = o.matrix_local.to_quaternion()
        scale = o.matrix_local.to_scale()
    else:
        translation = o.location
        quaternion = o.rotation_quaternion
        if o.rotation_mode != 'QUATERNION':
            quaternion = o.rotation_euler.to_quaternion()
        scale = o.scale

    json.write(b',"translation": [')
    json.write(str(translation.x).encode())
    json.write(b',')
    json.write(str(translation.z).encode())
    json.write(b',')
    json.write(str(-translation.y).encode())
    json.write(b']')

    json.write(b',"rotation": [')
    json.write(str(quaternion.x).encode())
    json.write(b',')
    json.write(str(quaternion.z).encode())
    json.write(b',')
    json.write(str(-quaternion.y).encode())
    json.write(b',')
    json.write(str(quaternion.w).encode())
    json.write(b']')

    json.write(b',"scale": [')
    json.write(str(scale.x).encode())
    json.write(b',')
    json.write(str(scale.z).encode())
    json.write(b',')
    json.write(str(scale.y).encode())
    json.write(b']')

    if type(o) == bpy.types.Object and o.type == 'MESH':
        meshes.append(o.data)
        json.write(b',"mesh": ')
        json.write(str(meshes.index(o.data)).encode())

    children = [x for x in o.children]
    if type(o) == bpy.types.Object and o.type == 'ARMATURE':
        children += [b for b in o.data.bones if b.parent == None]

    # Child nodes   
    if o.children:
        json.write(b',"children":[')
        for c in range(len(o.children)):
            child = o.children[c]
            json.write(str(objs.index(child)).encode())
            if c < len(o.children) - 1:
                json.write(b',')
        json.write(b']')

    json.write(b'}')
    if i < len(objs) - 1:
        json.write(b',')

json.write(b'],')

# Meshes section
if meshes:
    json.write(b'"meshes":[')
    for i in range(len(meshes)):
        m = meshes[i]
        json.write(b'{"name":"')
        json.write(m.name.encode())
        json.write(b'","primitives":[]}')
        if i < len(meshes) - 1:
            json.write(b',')
    json.write(b'],')

# Scene section
json.write(b'"scene":0,\n')
json.write(b'"scenes":[{"name":"Scene","nodes":[')

root_objs = [o for o in objs if o.parent == None]
for i in range(len(root_objs)):
    o = root_objs[i]
    json.write(str(objs.index(o)).encode())
    if i < len(root_objs) - 1:
        json.write(b',')

json.write(b']}]\n')
json.write(b'}')

# JSON must be aligned to 4-byte
while json.tell() % 4 != 0:
    json.write(str(" ").encode())

json = json.getbuffer()
output.write(np.uint32(len(json)))
output.write(np.uint32(0x4E4F534A))
output.write(json)



# for a in bpy.data.actions:
#    output.write(f'{a.name}\n'.encode())
#    
#    for f in a.fcurves:
#        output.write(f'{f.data_path}\n'.encode())
#    
#        for k in f.keyframe_points:
#            output.write(struct.pack('!f', k.co[0]))
#            output.write(struct.pack('!f', k.co[1]))

f = open('output.glb', 'wb')
f.write(output.getbuffer())
output.close()
f.close()

print(time.time() - start)
