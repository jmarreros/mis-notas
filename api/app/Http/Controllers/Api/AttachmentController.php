<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\Attachment;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Storage;
use Symfony\Component\HttpFoundation\StreamedResponse;

class AttachmentController extends Controller
{
    public function store(Request $request): JsonResponse
    {
        $data = $request->validate([
            'id' => ['required', 'uuid'],
            'note_id' => ['nullable', 'uuid'],
            'file' => ['required', 'file', 'image:allow_svg', 'max:20480'],
        ]);

        $existing = Attachment::find($data['id']);
        if ($existing) {
            abort_unless($existing->user_id === $request->user()->id, 409);

            return response()->json($existing);
        }

        $file = $data['file'];
        $path = $file->storeAs(
            'attachments/'.$request->user()->id,
            $data['id'].'.'.($file->extension() ?: 'bin'),
        );

        $attachment = Attachment::create([
            'id' => $data['id'],
            'user_id' => $request->user()->id,
            'note_id' => $data['note_id'] ?? null,
            'path' => $path,
            'mime' => $file->getMimeType(),
            'size' => $file->getSize(),
        ]);

        return response()->json($attachment, 201);
    }

    public function show(Request $request, string $id): StreamedResponse
    {
        $attachment = Attachment::where('user_id', $request->user()->id)->findOrFail($id);

        return Storage::response($attachment->path, null, [
            'Content-Type' => $attachment->mime,
            'Cache-Control' => 'private, max-age=31536000, immutable',
        ]);
    }
}
