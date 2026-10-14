<?php

namespace Tests\Feature;

use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\UploadedFile;
use Illuminate\Support\Facades\Storage;
use Illuminate\Support\Str;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class AttachmentTest extends TestCase
{
    use RefreshDatabase;

    public function test_upload_and_download(): void
    {
        Storage::fake();
        Sanctum::actingAs(User::factory()->create());
        $id = (string) Str::uuid();

        $this->post('/api/attachments', ['id' => $id, 'file' => UploadedFile::fake()->image('mapa.png')], ['Accept' => 'application/json'])
            ->assertCreated()->assertJsonPath('id', $id)->assertJsonMissingPath('path');

        // Reintento idempotente.
        $this->post('/api/attachments', ['id' => $id, 'file' => UploadedFile::fake()->image('mapa.png')], ['Accept' => 'application/json'])
            ->assertOk();

        $this->get("/api/attachments/{$id}")->assertOk()->assertHeader('Content-Type', 'image/png');

        Sanctum::actingAs(User::factory()->create());
        $this->getJson("/api/attachments/{$id}")->assertNotFound();
    }

    public function test_rejects_non_images(): void
    {
        Storage::fake();
        Sanctum::actingAs(User::factory()->create());
        $this->post('/api/attachments', ['id' => (string) Str::uuid(), 'file' => UploadedFile::fake()->create('x.pdf', 10, 'application/pdf')], ['Accept' => 'application/json'])
            ->assertUnprocessable();
    }
}
